//! bare digit vision 验证 prompt 模板。
//! ←→ FNM_RE/modules/llm_bare_digit_verify.py 中的 prompt 部分

/// 构建 vision LLM prompt，判断指定数字是否为正文中的注释标记上标。
pub fn build_bare_digit_prompt(marker: &str, context_snippet: &str) -> String {
    format!(
        "查看页面截图。数字 \"{}\" 是否是正文中的注释标记上标？\n\
        \n\
        附近文本：\"{}\"\n\
        \n\
        - 如果是上标（例如位于词后右上角的小字号数字），回复 JSON: {{\"is_superscript\": true, \"confidence\": 0.9}}\n\
        - 如果是正文普通数字（如页码、年份、列表编号），回复 JSON: {{\"is_superscript\": false, \"confidence\": 0.9}}\n",
        marker, context_snippet
    )
}
