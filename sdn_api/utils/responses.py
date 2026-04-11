import json
from webob import Response


def json_response(data, status=200):
    return Response(
        status=status,
        content_type="application/json",
        charset="utf-8",
        body=json.dumps(data).encode("utf-8"),
        headers=[
            ("Access-Control-Allow-Origin", "*"),
            ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
            ("Access-Control-Allow-Headers", "Content-Type, Accept")
        ]
    )


def cors_preflight():
    return Response(
        status=200,
        headers=[
            ("Access-Control-Allow-Origin", "*"),
            ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
            ("Access-Control-Allow-Headers", "Content-Type, Accept"),
            ("Content-Length", "0")
        ]
    )


def error_response(error, status=400):
    return json_response({
        "ok": False,
        "error": str(error)
    }, status=status)


def success_response(data, status=200):
    return json_response({
        "ok": True,
        "data": data
    }, status=status)