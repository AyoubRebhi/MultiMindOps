from fastapi import APIRouter, Header, HTTPException, Query

from backend.app.services.github_service import GitHubService

router = APIRouter(prefix="/artifacts", tags=["Artifacts"])
github_service = GitHubService()


@router.get("/view")
def view_artifact(
    repo_url: str = Query(..., description="GitHub repository URL"),
    path: str = Query(..., description="Repository-relative file path"),
    branch: str = Query("main", description="Git branch to read from"),
    repository_visibility: str = Query("public", description="public or private"),
    github_token: str | None = Header(default=None, alias="X-GitHub-Token"),
):
    try:
        return github_service.get_repository_file_content(
            repo_url=repo_url,
            file_path=path,
            branch=branch or "main",
            repository_visibility=repository_visibility,
            github_token=github_token,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        detail = str(exc)
        status_code = 413 if "too large" in detail.lower() else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Unable to retrieve artifact content: {exc}",
        ) from exc
