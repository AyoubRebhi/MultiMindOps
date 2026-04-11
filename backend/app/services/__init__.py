"""Business logic services for the backend.

Services are organized by domain:
- cicd:           CI/CD pipeline and artifact services
- repository:     Repository analysis and source control services
- environment:    Environment variable management services
- rag:            RAG context and template retrieval services
- infrastructure: Infrastructure artifact and dependency services
- execution:      Command detection and execution trace services
- core:           Foundational services (LLM, tasks, API keys)
"""

from backend.app.services.cicd import (
    ArtifactContractService,
    ArtifactQualityValidator,
    CicdContractValidationService,
    CicdHandoffService,
    CicdWorkflowBuilderService,
    GitHubActionsTemplateService,
)
from backend.app.services.repository import (
    GitHubService,
    RepositoryFingerprintService,
    RepositoryParserService,
    RepositoryRegistryService,
    RepositorySecurityService,
    RuntimeDetectorService,
    ServiceDetectorService,
)
from backend.app.services.environment import (
    EnvFileDetectorService,
    EnvHashingService,
    EnvSanitizerService,
    EnvironmentVariableExtractorService,
    UploadedEnvFileService,
)
from backend.app.services.rag import (
    ChunkingService,
    ContextBuilderService,
    TemplateCorpusService,
    TemplateRetrievalService,
)
from backend.app.services.infrastructure import (
    InfraDependencyDetectorService,
    InfrastructureArtifactBuilderService,
    InfrastructureContextMapper,
)
from backend.app.services.execution import (
    CommandDetectorService,
    ExecutionTraceService,
)
from backend.app.services.core import (
    GroqKeyManager,
    LLMService,
    TaskService,
)

__all__ = [
    # cicd
    "ArtifactContractService",
    "ArtifactQualityValidator",
    "CicdContractValidationService",
    "CicdHandoffService",
    "CicdWorkflowBuilderService",
    "GitHubActionsTemplateService",
    # repository
    "GitHubService",
    "RepositoryFingerprintService",
    "RepositoryParserService",
    "RepositoryRegistryService",
    "RepositorySecurityService",
    "RuntimeDetectorService",
    "ServiceDetectorService",
    # environment
    "EnvFileDetectorService",
    "EnvHashingService",
    "EnvSanitizerService",
    "EnvironmentVariableExtractorService",
    "UploadedEnvFileService",
    # rag
    "ChunkingService",
    "ContextBuilderService",
    "TemplateCorpusService",
    "TemplateRetrievalService",
    # infrastructure
    "InfraDependencyDetectorService",
    "InfrastructureArtifactBuilderService",
    "InfrastructureContextMapper",
    # execution
    "CommandDetectorService",
    "ExecutionTraceService",
    # core
    "GroqKeyManager",
    "LLMService",
    "TaskService",
]
