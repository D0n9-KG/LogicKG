import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.rag.models import AskV2Request, AskV2Response
from app.rag.service import ask_v2, ask_v2_stream


router = APIRouter(prefix="/rag", tags=["rag"])


def _scope_payload(req: AskV2Request) -> dict | None:
    return req.scope.model_dump() if req.scope else None


@router.post("/ask_v2", response_model=AskV2Response)
def rag_ask_v2(req: AskV2Request):
    try:
        return ask_v2(
            req.question,
            k=req.k,
            scope=_scope_payload(req),
            locale=req.locale,
            domain_prompt=req.domain_prompt,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/ask", response_model=AskV2Response)
def rag_ask(req: AskV2Request):
    # /rag/ask is now fully cut over to ask_v2 internals.
    try:
        return ask_v2(
            req.question,
            k=req.k,
            scope=_scope_payload(req),
            locale=req.locale,
            domain_prompt=req.domain_prompt,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _sse_encode(event: str, data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


@router.post("/ask_v2_stream")
def rag_ask_v2_stream(req: AskV2Request):
    def event_iter():
        try:
            for event, payload in ask_v2_stream(
                req.question,
                k=req.k,
                scope=_scope_payload(req),
                locale=req.locale,
                domain_prompt=req.domain_prompt,
            ):
                yield _sse_encode(event, payload)
        except FileNotFoundError as exc:
            yield _sse_encode("error", {"error": str(exc), "code": "file_not_found"})
        except Exception as exc:
            yield _sse_encode("error", {"error": str(exc), "code": "internal_error"})

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(event_iter(), media_type="text/event-stream", headers=headers)
