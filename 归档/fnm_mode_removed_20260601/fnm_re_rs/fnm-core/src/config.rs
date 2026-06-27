//! ←→ /Users/hao/OCRandTranslation/config.py (~1500 行)
//! 应用配置：API key 读取 + fnm/translation model pool 读取。
//!
//! 仅 port FNM_RE → Rust pipeline 所需的配置项：
//! - 5 家 provider 的 API key
//! - fnm_model_pool / translation_model_pool 槽位读取
//! - 基础 base_url 常量

use crate::model_capabilities::normalize_builtin_model_key;
use once_cell::sync::Lazy;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::RwLock;

// ── 常量：base URL ──────────────────────────────────────────────

pub static QWEN_BASE_URLS: Lazy<HashMap<&'static str, &'static str>> = Lazy::new(|| {
    let mut m = HashMap::new();
    m.insert("cn", "https://dashscope.aliyuncs.com/compatible-mode/v1");
    m.insert(
        "sg",
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    );
    m.insert("us", "https://dashscope-us.aliyuncs.com/compatible-mode/v1");
    m
});

pub const DEEPSEEK_BASE_URL: &str = "https://api.deepseek.com";
pub const MIMO_BASE_URL: &str = "https://api.xiaomimimo.com/v1";
pub const MIMO_TOKEN_PLAN_BASE_URL_DEFAULT: &str = "https://token-plan-sgp.xiaomimimo.com/v1";
pub const GLM_BASE_URL: &str = "https://open.bigmodel.cn/api/paas/v4/";
pub const KIMI_BASE_URL: &str = "https://api.moonshot.ai/v1";
pub const GEMINI_BASE_URL: &str = "https://generativelanguage.googleapis.com/v1beta/openai/";

pub const MODEL_POOL_SLOT_COUNT: usize = 4;
pub const ACTIVE_BUILTIN_MODEL_KEY_DEFAULT: &str = "deepseek-chat";
pub const ACTIVE_BUILTIN_FNM_MODEL_KEY_DEFAULT: &str = "qwen3.6-plus";

// ── 数据结构 ─────────────────────────────────────────────────────

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ModelPoolSlot {
    #[serde(default = "default_empty")]
    pub mode: String, // "builtin" / "custom" / "empty"
    #[serde(default)]
    pub builtin_key: String,
    #[serde(default)]
    pub display_name: String,
    #[serde(default = "default_qwen")]
    pub provider_type: String,
    #[serde(default)]
    pub model_id: String,
    #[serde(default)]
    pub base_url: String,
    #[serde(default = "default_cn")]
    pub qwen_region: String,
    #[serde(default)]
    pub custom_api_key: String,
    #[serde(default)]
    pub extra_body: Value,
    #[serde(default)]
    pub thinking_enabled: bool,
}

fn default_empty() -> String {
    "empty".into()
}
fn default_qwen() -> String {
    "qwen".into()
}
fn default_cn() -> String {
    "cn".into()
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct AppConfig {
    #[serde(default)]
    pub deepseek_key: String,
    #[serde(default)]
    pub dashscope_key: String,
    #[serde(default)]
    pub mimo_api_key: String,
    #[serde(default)]
    pub glm_api_key: String,
    #[serde(default)]
    pub kimi_api_key: String,
    #[serde(default)]
    pub gemini_key: String,
    #[serde(default)]
    pub fnm_repair_primary_model_id: String,
    #[serde(default)]
    pub fnm_repair_final_model_id: String,
    #[serde(default)]
    pub translation_model_pool: Vec<ModelPoolSlot>,
    #[serde(default)]
    pub fnm_model_pool: Vec<ModelPoolSlot>,
}

// ── 路径 ─────────────────────────────────────────────────────────

/// 项目根目录：Cargo 工程上溯到包含 local_data/ 的目录。
fn project_root() -> PathBuf {
    if let Ok(path) = std::env::var("FNM_RE_PROJECT_ROOT") {
        return PathBuf::from(path);
    }
    let mut cur = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    for _ in 0..6 {
        if cur.join("local_data").exists() || cur.join("config.py").exists() {
            return cur;
        }
        match cur.parent() {
            Some(p) => cur = p.to_path_buf(),
            None => break,
        }
    }
    PathBuf::from(".")
}

fn config_file_path() -> PathBuf {
    project_root()
        .join("local_data")
        .join("user_data")
        .join("config.json")
}

// ── 加载与缓存 ──────────────────────────────────────────────────

static CONFIG_CACHE: Lazy<RwLock<Option<AppConfig>>> = Lazy::new(|| RwLock::new(None));

/// 从磁盘加载 config.json；失败返回 default。
pub fn load_config() -> AppConfig {
    if let Ok(cache) = CONFIG_CACHE.read() {
        if let Some(cfg) = cache.as_ref() {
            return cfg.clone();
        }
    }
    let path = config_file_path();
    let cfg = if path.exists() {
        std::fs::read_to_string(&path)
            .ok()
            .and_then(|s| serde_json::from_str::<AppConfig>(&s).ok())
            .unwrap_or_default()
    } else {
        AppConfig::default()
    };
    if let Ok(mut cache) = CONFIG_CACHE.write() {
        *cache = Some(cfg.clone());
    }
    cfg
}

/// 清空 cache（测试或重载时使用）。
pub fn invalidate_config_cache() {
    if let Ok(mut cache) = CONFIG_CACHE.write() {
        *cache = None;
    }
}

// ── 默认 pool（首次加载或迁移后） ─────────────────────────────

fn default_pool_slot() -> ModelPoolSlot {
    ModelPoolSlot {
        mode: "empty".into(),
        builtin_key: String::new(),
        display_name: String::new(),
        provider_type: "qwen".into(),
        model_id: String::new(),
        base_url: String::new(),
        qwen_region: "cn".into(),
        custom_api_key: String::new(),
        extra_body: Value::Null,
        thinking_enabled: false,
    }
}

/// 默认 fnm pool：slot[0] builtin（key 非空），其余 empty。无用户配置时使用。
fn default_fnm_model_pool() -> Vec<ModelPoolSlot> {
    let mut slots = vec![default_pool_slot(); MODEL_POOL_SLOT_COUNT];
    slots[0].mode = "builtin".into();
    slots[0].builtin_key =
        normalize_builtin_model_key(ACTIVE_BUILTIN_FNM_MODEL_KEY_DEFAULT, Some("fnm"));
    slots
}

/// 返回当前 fnm pool（如未配置则给一个默认 builtin 槽 + 空槽位）。
pub fn get_fnm_model_pool() -> Vec<ModelPoolSlot> {
    let cfg = load_config();
    if cfg.fnm_model_pool.is_empty() {
        return default_fnm_model_pool();
    }
    cfg.fnm_model_pool
}

/// 返回当前 translation pool（如未配置则给一个默认 builtin 槽 + 空槽位）。
pub fn get_translation_model_pool() -> Vec<ModelPoolSlot> {
    let cfg = load_config();
    if cfg.translation_model_pool.is_empty() {
        let mut slots = vec![default_pool_slot(); MODEL_POOL_SLOT_COUNT];
        slots[0].mode = "builtin".into();
        slots[0].builtin_key =
            normalize_builtin_model_key(ACTIVE_BUILTIN_MODEL_KEY_DEFAULT, Some("translation"));
        return slots;
    }
    cfg.translation_model_pool
}

// ── API key 取值（按 provider 路由，支持环境变量 fallback）──────

pub fn get_deepseek_key() -> String {
    let cfg = load_config();
    if !cfg.deepseek_key.is_empty() {
        return cfg.deepseek_key;
    }
    std::env::var("DEEPSEEK_API_KEY").unwrap_or_default()
}

pub fn get_dashscope_key() -> String {
    let cfg = load_config();
    if !cfg.dashscope_key.is_empty() {
        return cfg.dashscope_key;
    }
    std::env::var("DASHSCOPE_API_KEY").unwrap_or_default()
}

pub fn get_mimo_api_key() -> String {
    let cfg = load_config();
    if !cfg.mimo_api_key.is_empty() {
        return cfg.mimo_api_key;
    }
    std::env::var("MIMO_API_KEY").unwrap_or_default()
}

pub fn get_glm_api_key() -> String {
    let cfg = load_config();
    if !cfg.glm_api_key.is_empty() {
        return cfg.glm_api_key;
    }
    std::env::var("GLM_API_KEY").unwrap_or_default()
}

pub fn get_kimi_api_key() -> String {
    let cfg = load_config();
    if !cfg.kimi_api_key.is_empty() {
        return cfg.kimi_api_key;
    }
    std::env::var("KIMI_API_KEY").unwrap_or_default()
}

pub fn get_gemini_key() -> String {
    let cfg = load_config();
    if !cfg.gemini_key.is_empty() {
        return cfg.gemini_key;
    }
    std::env::var("GEMINI_API_KEY").unwrap_or_default()
}

pub fn get_fnm_repair_primary_model_id() -> String {
    load_config().fnm_repair_primary_model_id.trim().to_string()
}

pub fn get_fnm_repair_final_model_id() -> String {
    load_config().fnm_repair_final_model_id.trim().to_string()
}

/// ←→ Python `_thinking_payload_for_provider`
pub fn thinking_payload_for_provider(provider: &str, enabled: bool, request_format: &str) -> Value {
    let p = provider.trim().to_lowercase();
    let f = request_format.trim().to_lowercase();
    if f == "qwen_enable_thinking" || p == "qwen" {
        return serde_json::json!({ "enable_thinking": enabled });
    }
    if f == "thinking_type"
        || matches!(
            p.as_str(),
            "deepseek" | "glm" | "kimi" | "mimo" | "mimo_token_plan"
        )
    {
        return serde_json::json!({
            "thinking": { "type": if enabled { "enabled" } else { "disabled" } }
        });
    }
    Value::Null
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_pool_has_4_slots_with_builtin_at_zero() {
        // 直接验证默认 pool 构造逻辑，不依赖全局 config——用户可能已配置 custom
        // pool，那时 get_fnm_model_pool 返回用户 pool（slot[0] 非 builtin）。
        let pool = default_fnm_model_pool();
        assert_eq!(pool.len(), MODEL_POOL_SLOT_COUNT);
        assert_eq!(pool[0].mode, "builtin");
        assert!(!pool[0].builtin_key.is_empty());
        assert!(pool[1..].iter().all(|s| s.mode == "empty"));
    }

    #[test]
    fn thinking_payload_qwen() {
        let v = thinking_payload_for_provider("qwen", true, "");
        assert_eq!(v["enable_thinking"], serde_json::json!(true));
    }

    #[test]
    fn thinking_payload_deepseek() {
        let v = thinking_payload_for_provider("deepseek", true, "");
        assert_eq!(v["thinking"]["type"], serde_json::json!("enabled"));
    }

    #[test]
    fn thinking_payload_unsupported_returns_null() {
        let v = thinking_payload_for_provider("unknown", true, "");
        assert!(v.is_null());
    }

    #[test]
    fn base_urls_present() {
        assert!(QWEN_BASE_URLS.contains_key("cn"));
        assert_eq!(DEEPSEEK_BASE_URL, "https://api.deepseek.com");
    }
}
