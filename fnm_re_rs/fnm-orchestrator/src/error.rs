//! Orchestrator 统一错误类型。←→ Python pipeline 异常分类。

use thiserror::Error;

#[derive(Debug, Error)]
pub enum OrchestratorError {
    #[error("phase1 build failed: {0}")]
    Phase1(#[source] anyhow::Error),

    #[error("phase2 build failed: {0}")]
    Phase2(#[source] anyhow::Error),

    #[error("phase3 build failed: {0}")]
    Phase3(#[source] anyhow::Error),

    #[error("phase4 build failed: {0}")]
    Phase4(#[source] anyhow::Error),

    #[error("phase5 build failed: {0}")]
    Phase5(#[source] anyhow::Error),

    #[error("phase6 build failed: {0}")]
    Phase6(#[source] anyhow::Error),

    #[error("llm repair failed: {0}")]
    LlmRepair(#[source] anyhow::Error),

    #[error("invalid start_phase: {0}")]
    InvalidStartPhase(String),

    #[error("invalid config: {0}")]
    InvalidConfig(String),
}

pub type Result<T> = std::result::Result<T, OrchestratorError>;
