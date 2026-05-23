//! ←→ /Users/hao/OCRandTranslation/model_capabilities.py (599 行)
//! 内置模型目录与能力描述（DeepSeek / Qwen / MiMo / GLM / Kimi 五家共 ~40 个 spec）。

use once_cell::sync::Lazy;
use std::collections::HashMap;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ApiFamily {
    Chat,
    Mt,
    Vision,
}

impl ApiFamily {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Chat => "chat",
            Self::Mt => "mt",
            Self::Vision => "vision",
        }
    }

    pub fn parse(s: &str) -> Self {
        match s.trim() {
            "mt" => Self::Mt,
            "vision" => Self::Vision,
            _ => Self::Chat,
        }
    }
}

#[derive(Debug, Clone)]
pub struct ModelSpec {
    pub id: String,
    pub label: String,
    pub provider: String,
    pub api_family: ApiFamily,
    pub supports_translation: bool,
    pub supports_vision: bool,
    pub supports_stream: bool,
    pub stream_mode: String,
    pub companion_chat_model_key: String,
    pub translation_selectable: bool,
    pub fnm_selectable: bool,
    pub visual_selectable: bool,
    pub supports_thinking_toggle: bool,
    pub thinking_request_format: String,
}

fn chat_model(
    id: &str,
    label: &str,
    provider: &str,
    selectable: bool,
    thinking: bool,
    companion: Option<&str>,
) -> ModelSpec {
    ModelSpec {
        id: id.to_string(),
        label: label.to_string(),
        provider: provider.to_string(),
        api_family: ApiFamily::Chat,
        supports_translation: true,
        supports_vision: false,
        supports_stream: true,
        stream_mode: "chat_json".into(),
        companion_chat_model_key: companion.unwrap_or(id).to_string(),
        translation_selectable: selectable,
        fnm_selectable: false,
        visual_selectable: false,
        supports_thinking_toggle: thinking,
        thinking_request_format: if thinking {
            if provider == "qwen" {
                "qwen_enable_thinking".into()
            } else {
                "thinking_type".into()
            }
        } else {
            String::new()
        },
    }
}

fn mt_model(
    id: &str,
    label: &str,
    stream_mode: &str,
    companion: &str,
    selectable: bool,
) -> ModelSpec {
    ModelSpec {
        id: id.to_string(),
        label: label.to_string(),
        provider: "qwen_mt".into(),
        api_family: ApiFamily::Mt,
        supports_translation: true,
        supports_vision: false,
        supports_stream: true,
        stream_mode: stream_mode.to_string(),
        companion_chat_model_key: companion.to_string(),
        translation_selectable: selectable,
        fnm_selectable: false,
        visual_selectable: false,
        supports_thinking_toggle: false,
        thinking_request_format: String::new(),
    }
}

fn vision_model(
    id: &str,
    label: &str,
    provider: &str,
    selectable: bool,
    translation_selectable: bool,
    thinking: bool,
    companion: Option<&str>,
    supports_translation: bool,
) -> ModelSpec {
    ModelSpec {
        id: id.to_string(),
        label: label.to_string(),
        provider: provider.to_string(),
        api_family: ApiFamily::Vision,
        supports_translation,
        supports_vision: true,
        supports_stream: true,
        stream_mode: "chat_json".into(),
        companion_chat_model_key: companion.unwrap_or(id).to_string(),
        translation_selectable,
        fnm_selectable: selectable,
        visual_selectable: selectable,
        supports_thinking_toggle: thinking,
        thinking_request_format: if thinking {
            if provider == "qwen" {
                "qwen_enable_thinking".into()
            } else {
                "thinking_type".into()
            }
        } else {
            String::new()
        },
    }
}

pub static MODEL_SPECS: Lazy<HashMap<String, ModelSpec>> = Lazy::new(|| {
    let mut m = HashMap::new();
    // DeepSeek
    m.insert(
        "deepseek-chat".into(),
        chat_model(
            "deepseek-chat",
            "DeepSeek-Chat",
            "deepseek",
            true,
            true,
            None,
        ),
    );
    m.insert(
        "deepseek-reasoner".into(),
        chat_model(
            "deepseek-reasoner",
            "DeepSeek-Reasoner",
            "deepseek",
            true,
            false,
            None,
        ),
    );

    // Qwen 3.6 系列
    m.insert(
        "qwen3.6-max-preview".into(),
        chat_model(
            "qwen3.6-max-preview",
            "Qwen3.6 Max Preview",
            "qwen",
            true,
            true,
            Some("qwen3.6-plus"),
        ),
    );
    m.insert(
        "qwen3.6-plus".into(),
        vision_model(
            "qwen3.6-plus",
            "Qwen3.6 Plus",
            "qwen",
            true,
            true,
            true,
            None,
            true,
        ),
    );
    m.insert(
        "qwen3.6-flash".into(),
        vision_model(
            "qwen3.6-flash",
            "Qwen3.6 Flash",
            "qwen",
            true,
            true,
            true,
            None,
            true,
        ),
    );

    // Qwen 3.5 系列
    m.insert(
        "qwen3.5-plus".into(),
        vision_model(
            "qwen3.5-plus",
            "Qwen3.5 Plus",
            "qwen",
            true,
            true,
            true,
            None,
            true,
        ),
    );
    m.insert(
        "qwen3.5-flash".into(),
        vision_model(
            "qwen3.5-flash",
            "Qwen3.5 Flash",
            "qwen",
            true,
            true,
            true,
            None,
            true,
        ),
    );

    // Qwen 经典
    m.insert(
        "qwen-plus".into(),
        chat_model("qwen-plus", "Qwen-Plus", "qwen", false, true, None),
    );
    m.insert(
        "qwen-max".into(),
        chat_model(
            "qwen-max",
            "Qwen-Max",
            "qwen",
            false,
            true,
            Some("qwen-plus"),
        ),
    );
    m.insert(
        "qwen-turbo".into(),
        chat_model("qwen-turbo", "Qwen-Turbo", "qwen", false, true, None),
    );

    // Qwen MT
    m.insert(
        "qwen-mt-plus".into(),
        mt_model(
            "qwen-mt-plus",
            "Qwen-MT-Plus",
            "mt_cumulative",
            "qwen3.6-plus",
            true,
        ),
    );
    m.insert(
        "qwen-mt-turbo".into(),
        mt_model(
            "qwen-mt-turbo",
            "Qwen-MT-Turbo",
            "mt_cumulative",
            "qwen3.6-flash",
            true,
        ),
    );
    m.insert(
        "qwen-mt-flash".into(),
        mt_model(
            "qwen-mt-flash",
            "Qwen-MT-Flash",
            "mt_incremental",
            "qwen3.6-flash",
            true,
        ),
    );
    m.insert(
        "qwen-mt-lite".into(),
        mt_model(
            "qwen-mt-lite",
            "Qwen-MT-Lite",
            "mt_incremental",
            "qwen3.6-flash",
            false,
        ),
    );

    // Qwen VL
    m.insert(
        "qwen3-vl-plus".into(),
        vision_model(
            "qwen3-vl-plus",
            "Qwen3 VL Plus",
            "qwen",
            true,
            false,
            true,
            Some("qwen3.6-plus"),
            true,
        ),
    );
    m.insert(
        "qwen3-vl-flash".into(),
        vision_model(
            "qwen3-vl-flash",
            "Qwen3 VL Flash",
            "qwen",
            true,
            false,
            true,
            Some("qwen3.6-flash"),
            true,
        ),
    );
    m.insert(
        "qwen-vl-plus".into(),
        vision_model(
            "qwen-vl-plus",
            "Qwen-VL-Plus",
            "qwen",
            false,
            false,
            false,
            Some("qwen-plus"),
            false,
        ),
    );
    m.insert(
        "qwen-vl-max".into(),
        vision_model(
            "qwen-vl-max",
            "Qwen-VL-Max",
            "qwen",
            false,
            false,
            false,
            Some("qwen-plus"),
            false,
        ),
    );
    m.insert(
        "qwen-vl-ocr".into(),
        vision_model(
            "qwen-vl-ocr",
            "Qwen-VL-OCR",
            "qwen",
            false,
            false,
            false,
            Some("qwen-plus"),
            false,
        ),
    );

    // MiMo
    m.insert(
        "mimo-v2-flash".into(),
        chat_model("mimo-v2-flash", "MiMo V2 Flash", "mimo", true, false, None),
    );
    m.insert(
        "mimo-v2-pro".into(),
        chat_model("mimo-v2-pro", "MiMo V2 Pro", "mimo", true, true, None),
    );
    m.insert(
        "mimo-v2.5-pro".into(),
        chat_model("mimo-v2.5-pro", "MiMo V2.5 Pro", "mimo", true, true, None),
    );
    m.insert(
        "mimo-v2.5".into(),
        vision_model(
            "mimo-v2.5",
            "MiMo V2.5",
            "mimo",
            true,
            false,
            true,
            None,
            true,
        ),
    );
    m.insert(
        "mimo-v2-omni".into(),
        vision_model(
            "mimo-v2-omni",
            "MiMo V2 Omni",
            "mimo",
            true,
            false,
            true,
            Some("mimo-v2.5"),
            true,
        ),
    );

    // GLM
    m.insert(
        "glm-5.1".into(),
        chat_model("glm-5.1", "GLM-5.1", "glm", true, true, None),
    );
    m.insert(
        "glm-5".into(),
        chat_model("glm-5", "GLM-5", "glm", true, true, None),
    );
    m.insert(
        "glm-5-turbo".into(),
        chat_model("glm-5-turbo", "GLM-5-Turbo", "glm", true, true, None),
    );
    m.insert(
        "glm-4.7".into(),
        chat_model("glm-4.7", "GLM-4.7", "glm", false, true, None),
    );
    m.insert(
        "glm-4.6".into(),
        chat_model("glm-4.6", "GLM-4.6", "glm", false, true, None),
    );
    m.insert(
        "glm-4.7-flashx".into(),
        chat_model("glm-4.7-flashx", "GLM-4.7-FlashX", "glm", false, true, None),
    );
    m.insert(
        "glm-4.5".into(),
        chat_model("glm-4.5", "GLM-4.5", "glm", false, true, None),
    );
    m.insert(
        "glm-4.5-air".into(),
        chat_model("glm-4.5-air", "GLM-4.5-Air", "glm", false, true, None),
    );
    m.insert(
        "glm-4.5-airx".into(),
        chat_model("glm-4.5-airx", "GLM-4.5-AirX", "glm", false, true, None),
    );
    m.insert(
        "glm-4-long".into(),
        chat_model("glm-4-long", "GLM-4-Long", "glm", false, false, None),
    );
    m.insert(
        "glm-5v-turbo".into(),
        vision_model(
            "glm-5v-turbo",
            "GLM-5V-Turbo",
            "glm",
            true,
            false,
            true,
            Some("glm-5.1"),
            true,
        ),
    );
    m.insert(
        "glm-4.6v".into(),
        vision_model(
            "glm-4.6v",
            "GLM-4.6V",
            "glm",
            true,
            false,
            true,
            Some("glm-4.6"),
            true,
        ),
    );
    m.insert(
        "glm-4.5v".into(),
        vision_model(
            "glm-4.5v",
            "GLM-4.5V",
            "glm",
            false,
            false,
            true,
            Some("glm-4.5"),
            true,
        ),
    );

    // Kimi
    m.insert(
        "kimi-k2.6".into(),
        vision_model(
            "kimi-k2.6",
            "Kimi K2.6",
            "kimi",
            true,
            true,
            true,
            None,
            true,
        ),
    );
    m.insert(
        "kimi-k2.5".into(),
        vision_model(
            "kimi-k2.5",
            "Kimi K2.5",
            "kimi",
            true,
            true,
            true,
            None,
            true,
        ),
    );
    m.insert(
        "kimi-k2-0905-preview".into(),
        chat_model(
            "kimi-k2-0905-preview",
            "Kimi K2 0905 Preview",
            "kimi",
            false,
            false,
            None,
        ),
    );
    m.insert(
        "kimi-k2-0711-preview".into(),
        chat_model(
            "kimi-k2-0711-preview",
            "Kimi K2 0711 Preview",
            "kimi",
            false,
            false,
            None,
        ),
    );
    m.insert(
        "kimi-k2-turbo-preview".into(),
        chat_model(
            "kimi-k2-turbo-preview",
            "Kimi K2 Turbo Preview",
            "kimi",
            false,
            false,
            None,
        ),
    );
    m.insert(
        "kimi-k2-thinking".into(),
        chat_model(
            "kimi-k2-thinking",
            "Kimi K2 Thinking",
            "kimi",
            false,
            false,
            None,
        ),
    );
    m.insert(
        "kimi-k2-thinking-turbo".into(),
        chat_model(
            "kimi-k2-thinking-turbo",
            "Kimi K2 Thinking Turbo",
            "kimi",
            false,
            false,
            None,
        ),
    );
    m.insert(
        "moonshot-v1-8k".into(),
        chat_model(
            "moonshot-v1-8k",
            "Moonshot V1 8K",
            "kimi",
            false,
            false,
            None,
        ),
    );
    m.insert(
        "moonshot-v1-32k".into(),
        chat_model(
            "moonshot-v1-32k",
            "Moonshot V1 32K",
            "kimi",
            true,
            false,
            None,
        ),
    );
    m.insert(
        "moonshot-v1-128k".into(),
        chat_model(
            "moonshot-v1-128k",
            "Moonshot V1 128K",
            "kimi",
            true,
            false,
            None,
        ),
    );
    m.insert(
        "moonshot-v1-8k-vision-preview".into(),
        vision_model(
            "moonshot-v1-8k-vision-preview",
            "Moonshot V1 8K Vision Preview",
            "kimi",
            false,
            false,
            false,
            Some("moonshot-v1-8k"),
            false,
        ),
    );
    m.insert(
        "moonshot-v1-32k-vision-preview".into(),
        vision_model(
            "moonshot-v1-32k-vision-preview",
            "Moonshot V1 32K Vision Preview",
            "kimi",
            false,
            false,
            false,
            Some("moonshot-v1-32k"),
            false,
        ),
    );
    m.insert(
        "moonshot-v1-128k-vision-preview".into(),
        vision_model(
            "moonshot-v1-128k-vision-preview",
            "Moonshot V1 128K Vision Preview",
            "kimi",
            false,
            false,
            false,
            Some("moonshot-v1-128k"),
            false,
        ),
    );

    m
});

pub const DEFAULT_TRANSLATION_MODEL_KEY: &str = "deepseek-chat";
pub const DEFAULT_VISUAL_MODEL_KEY: &str = "qwen3.6-plus";

/// ←→ Python `normalize_builtin_model_key`
pub fn normalize_builtin_model_key(key: &str, capability: Option<&str>) -> String {
    let normalized = key.trim().to_string();
    let mut chosen = if MODEL_SPECS.contains_key(&normalized) {
        normalized
    } else {
        match capability {
            Some("vision") | Some("fnm") => DEFAULT_VISUAL_MODEL_KEY.to_string(),
            _ => DEFAULT_TRANSLATION_MODEL_KEY.to_string(),
        }
    };
    let spec = MODEL_SPECS.get(&chosen).cloned();
    if let (Some("translation"), Some(s)) = (capability, &spec) {
        if !s.supports_translation {
            chosen = DEFAULT_TRANSLATION_MODEL_KEY.to_string();
        }
    } else if let (Some("vision"), Some(s)) = (capability, &spec) {
        if !s.supports_vision {
            chosen = DEFAULT_VISUAL_MODEL_KEY.to_string();
        }
    } else if let (Some("fnm"), Some(s)) = (capability, &spec) {
        if !s.fnm_selectable {
            chosen = DEFAULT_VISUAL_MODEL_KEY.to_string();
        }
    }
    chosen
}

/// ←→ Python `get_model_spec`
pub fn get_model_spec(key: &str, capability: Option<&str>) -> Option<ModelSpec> {
    let normalized = normalize_builtin_model_key(key, capability);
    MODEL_SPECS.get(&normalized).cloned()
}

/// ←→ Python `infer_builtin_key_from_custom_model`
pub fn infer_builtin_key_from_custom_model(
    provider: &str,
    model_id: &str,
    capability: Option<&str>,
) -> String {
    let p = provider.trim().to_lowercase();
    let m = model_id.trim().to_lowercase();
    let pick = |s: &str| s.to_string();
    match p.as_str() {
        "qwen_mt" => {
            if m.contains("flash") {
                return pick("qwen-mt-flash");
            }
            if m.contains("lite") {
                return pick("qwen-mt-lite");
            }
            if m.contains("turbo") {
                return pick("qwen-mt-turbo");
            }
            pick("qwen-mt-plus")
        }
        "qwen" => {
            if m.contains("3.6-max") || m.contains("3-max") {
                return pick("qwen3.6-max-preview");
            }
            if m.contains("3.6-flash") {
                return pick("qwen3.6-flash");
            }
            if m.contains("3.6-plus") {
                return pick("qwen3.6-plus");
            }
            if m.contains("3.5-flash") {
                return pick("qwen3.5-flash");
            }
            if m.contains("3.5-plus") {
                return pick("qwen3.5-plus");
            }
            if m.contains("qwen3-vl-flash") {
                return pick("qwen3-vl-flash");
            }
            if m.contains("qwen3-vl-plus") {
                return pick("qwen3-vl-plus");
            }
            if m.contains("vl-ocr") {
                return pick("qwen-vl-ocr");
            }
            if m.contains("vl-max") {
                return pick("qwen-vl-max");
            }
            if m.contains("vl-plus") {
                return pick("qwen-vl-plus");
            }
            if m.contains("max") {
                return pick("qwen-max");
            }
            if m.contains("turbo") || m.contains("flash") {
                return pick("qwen-turbo");
            }
            pick("qwen3.6-plus")
        }
        "deepseek" => {
            if m.contains("reasoner") || m.ends_with("-r1") {
                return pick("deepseek-reasoner");
            }
            pick("deepseek-chat")
        }
        "glm" => {
            if m.contains("5v") {
                return pick("glm-5v-turbo");
            }
            if m.contains("4.6v") {
                return pick("glm-4.6v");
            }
            if m.contains("4.5v") {
                return pick("glm-4.5v");
            }
            if m.contains("5.1") {
                return pick("glm-5.1");
            }
            if m.contains("5-turbo") || m.contains("5 turbo") {
                return pick("glm-5-turbo");
            }
            if m.contains("4.7-flashx") || m.contains("4.7 flashx") {
                return pick("glm-4.7-flashx");
            }
            if m.contains("4.7") {
                return pick("glm-4.7");
            }
            if m.contains("4.6") {
                return pick("glm-4.6");
            }
            if m.contains("4.5-airx") || m.contains("4.5 airx") {
                return pick("glm-4.5-airx");
            }
            if m.contains("4.5-air") || m.contains("4.5 air") {
                return pick("glm-4.5-air");
            }
            if m.contains("4.5") {
                return pick("glm-4.5");
            }
            if m.contains("long") {
                return pick("glm-4-long");
            }
            pick("glm-5.1")
        }
        "kimi" => {
            if m.contains("128k-vision") {
                return pick("moonshot-v1-128k-vision-preview");
            }
            if m.contains("32k-vision") {
                return pick("moonshot-v1-32k-vision-preview");
            }
            if m.contains("8k-vision") {
                return pick("moonshot-v1-8k-vision-preview");
            }
            if m.contains("k2.6") {
                return pick("kimi-k2.6");
            }
            if m.contains("k2.5") {
                return pick("kimi-k2.5");
            }
            if m.contains("thinking-turbo") {
                return pick("kimi-k2-thinking-turbo");
            }
            if m.contains("thinking") {
                return pick("kimi-k2-thinking");
            }
            if m.contains("turbo") {
                return pick("kimi-k2-turbo-preview");
            }
            if m.contains("0711") {
                return pick("kimi-k2-0711-preview");
            }
            if m.contains("0905") || m.starts_with("kimi-k2") {
                return pick("kimi-k2-0905-preview");
            }
            if m.contains("128k") {
                return pick("moonshot-v1-128k");
            }
            if m.contains("32k") {
                return pick("moonshot-v1-32k");
            }
            pick("kimi-k2.6")
        }
        "mimo" | "mimo_token_plan" => {
            if m.contains("omni") {
                return pick("mimo-v2-omni");
            }
            if m.contains("2.5-pro") {
                return pick("mimo-v2.5-pro");
            }
            if m.contains("2.5") {
                return pick("mimo-v2.5");
            }
            if m.contains("flash") {
                return pick("mimo-v2-flash");
            }
            if m.contains("v2-pro") || m.ends_with("-pro") {
                return pick("mimo-v2-pro");
            }
            pick("mimo-v2.5")
        }
        _ => normalize_builtin_model_key("", capability),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_keys_exist() {
        assert!(MODEL_SPECS.contains_key(DEFAULT_TRANSLATION_MODEL_KEY));
        assert!(MODEL_SPECS.contains_key(DEFAULT_VISUAL_MODEL_KEY));
    }

    #[test]
    fn five_providers_present() {
        let providers: std::collections::HashSet<_> =
            MODEL_SPECS.values().map(|s| s.provider.clone()).collect();
        assert!(providers.contains("deepseek"));
        assert!(providers.contains("qwen"));
        assert!(providers.contains("glm"));
        assert!(providers.contains("kimi"));
        assert!(providers.contains("mimo"));
        assert!(providers.contains("qwen_mt"));
    }

    #[test]
    fn normalize_unknown_falls_back() {
        assert_eq!(
            normalize_builtin_model_key("not-a-real-model", Some("translation")),
            DEFAULT_TRANSLATION_MODEL_KEY
        );
        assert_eq!(
            normalize_builtin_model_key("not-a-real-model", Some("fnm")),
            DEFAULT_VISUAL_MODEL_KEY
        );
    }

    #[test]
    fn infer_qwen_vision_from_id() {
        assert_eq!(
            infer_builtin_key_from_custom_model("qwen", "qwen-vl-ocr", None),
            "qwen-vl-ocr"
        );
        assert_eq!(
            infer_builtin_key_from_custom_model("qwen", "qwen3.6-flash-x", None),
            "qwen3.6-flash"
        );
    }

    #[test]
    fn infer_deepseek_reasoner() {
        assert_eq!(
            infer_builtin_key_from_custom_model("deepseek", "deepseek-reasoner", None),
            "deepseek-reasoner"
        );
        assert_eq!(
            infer_builtin_key_from_custom_model("deepseek", "my-model-r1", None),
            "deepseek-reasoner"
        );
    }
}
