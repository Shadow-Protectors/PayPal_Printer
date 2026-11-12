from typing import Optional, Any
from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

class AppException(HTTPException):
    def __init__(
        self,
        arg1: Any = 500,
        arg2: Optional[str] = None,
        arg3: Optional[str] = None,
        status_code: Optional[int] = None,
        error_code: Optional[str] = None,
        message: Optional[str] = None,
        details: Optional[Any] = None
    ):
        if isinstance(arg1, int):
            final_status = status_code or arg1
            final_code = error_code or (arg2 if isinstance(arg2, str) else "ERROR")
            final_msg = message or (arg3 if isinstance(arg3, str) else "An application error occurred.")
        elif isinstance(arg1, str):
            final_msg = message or arg1
            final_status = status_code or (arg2 if isinstance(arg2, int) else 500)
            final_code = error_code or (arg3 if isinstance(arg3, str) else "APP_ERROR")
        else:
            final_status = status_code or 500
            final_code = error_code or "ERROR"
            final_msg = message or "An application error occurred."

        self.error_code = final_code
        self.message = final_msg
        self.details = details
        super().__init__(status_code=final_status, detail=final_msg)


def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    content = {
        "error": exc.error_code,
        "message": exc.message
    }
    if exc.details is not None:
        content["details"] = exc.details
    return JSONResponse(status_code=exc.status_code, content=content)

def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    from fastapi.encoders import jsonable_encoder
    first_error = exc.errors()[0] if exc.errors() else {"msg": "Validation error"}
    error_msg = first_error.get("msg", "Validation error")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "VALIDATION_ERROR",
            "message": error_msg,
            "details": [{"loc": list(error["loc"]), "type": error["type"], "msg": error["msg"]}
                        for error in exc.errors()]
        }
    )

def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "INTERNAL_SERVER_ERROR",
            "message": "An unexpected error occurred. Please try again later."
        }
    )
