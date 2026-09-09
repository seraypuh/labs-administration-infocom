import asyncio
import json
import logging
import random
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from prometheus_client import Counter, Histogram, make_asgi_app
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace.export import BatchSpanProcessor

resource = Resource.create({
    "service.name": "observability-demo"
})

provider = TracerProvider(resource=resource)

trace.set_tracer_provider(provider)

otlp_exporter = OTLPSpanExporter(
    endpoint="http://otel-collector:4317",
    insecure=True,
)

provider.add_span_processor(
    BatchSpanProcessor(otlp_exporter)
)

tracer = trace.get_tracer(__name__)


# -------------------------
# Logging
# -------------------------

class JSONFormatter(logging.Formatter):
    def format(self, record):
        span = trace.get_current_span()
        context = span.get_span_context()

        trace_id = (
            format(context.trace_id, "032x")
            if context.is_valid
            else None
        )

        return json.dumps({
            "level": record.levelname,
            "message": record.getMessage(),
            "trace_id": trace_id,
        })


logger = logging.getLogger("demo-service")
logger.setLevel(logging.INFO)

handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())

logger.handlers.clear()
logger.addHandler(handler)


# -------------------------
# Prometheus metrics
# -------------------------

REQUESTS = Counter(
    "http_requests_total",
    "Total number of HTTP requests",
    ["method", "path", "status"],
)

ERRORS = Counter(
    "http_errors_total",
    "Total number of HTTP 5xx responses",
    ["method", "path"],
)

RESPONSE_TIME = Histogram(
    "http_response_duration_seconds",
    "HTTP response duration in seconds",
    ["method", "path"],
)


# -------------------------
# Application
# -------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Service started")
    yield
    logger.info("Service stopped")


app = FastAPI(
    title="Observability Demo Service",
    lifespan=lifespan,
)


# -------------------------
# Middleware
# -------------------------

@app.middleware("http")
async def metrics_and_logging(request: Request, call_next):
    start = time.perf_counter()

    try:
        response = await call_next(request)
    except Exception:
        duration = time.perf_counter() - start

        ERRORS.labels(
            request.method,
            request.url.path,
        ).inc()

        RESPONSE_TIME.labels(
            request.method,
            request.url.path,
        ).observe(duration)

        logger.exception(
            f"Unhandled exception: {request.method} {request.url.path}"
        )

        raise

    duration = time.perf_counter() - start

    REQUESTS.labels(
        request.method,
        request.url.path,
        response.status_code,
    ).inc()

    RESPONSE_TIME.labels(
        request.method,
        request.url.path,
    ).observe(duration)

    if response.status_code >= 500:
        ERRORS.labels(
            request.method,
            request.url.path,
        ).inc()

    logger.info(
        f"{request.method} {request.url.path} "
        f"status={response.status_code} "
        f"duration={duration:.3f}s"
    )

    return response


# -------------------------
# Main page
# -------------------------

@app.get("/", response_class=HTMLResponse)
async def index():
    return """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <title>Observability Demo</title>
        <style>
            body {
                font-family: sans-serif;
                max-width: 700px;
                margin: 60px auto;
                padding: 20px;
            }

            button {
                display: block;
                width: 100%;
                margin: 15px 0;
                padding: 15px;
                font-size: 18px;
                cursor: pointer;
            }

            #result {
                margin-top: 30px;
                padding: 15px;
                background: #eee;
                white-space: pre-wrap;
            }
        </style>
    </head>

    <body>
        <h1>Observability Demo Service</h1>

        <button onclick="request('/error')">
            Создать ошибку
        </button>

        <button onclick="request('/delay')">
            Создать задержку
        </button>

        <button onclick="request('/load')">
            Нагрузка
        </button>

        <div id="result"></div>

        <script>
            async function request(url) {
                const result = document.getElementById("result");

                result.textContent = "Запрос...";

                try {
                    const response = await fetch(url);
                    const text = await response.text();

                    result.textContent =
                        "HTTP " + response.status + "\\n\\n" + text;
                } catch (error) {
                    result.textContent = error.toString();
                }
            }
        </script>
    </body>
    </html>
    """


# -------------------------
# Normal endpoint
# -------------------------

@app.get("/hello")
async def hello():
    return {
        "status": "ok"
    }


# -------------------------
# Error
# -------------------------

@app.get("/error")
async def error():
    logger.error("Intentional error generated")

    return JSONResponse(
        status_code=500,
        content={
            "error": "Intentional error"
        },
    )


# -------------------------
# Delay
# -------------------------

@app.get("/delay")
async def delay():
    delay_seconds = random.uniform(1, 3)

    logger.warning(
        f"Intentional delay: {delay_seconds:.2f}s"
    )

    with tracer.start_as_current_span("slow-dependency") as span:
        span.set_attribute(
            "delay.seconds",
            delay_seconds
        )

        await asyncio.sleep(delay_seconds)

    return {
        "status": "ok",
        "delay": round(delay_seconds, 2),
    }


# -------------------------
# Load
# -------------------------

async def make_request(client: httpx.AsyncClient):
    try:
        await client.get("/hello")
    except Exception as e:
        logger.error(f"Load request failed: {e}")


@app.get("/load")
async def load(request: Request):
    count = 30

    logger.warning(
        f"Generating load: {count} requests"
    )

    base_url = str(request.base_url).rstrip("/")

    async with httpx.AsyncClient(
        base_url=base_url,
        timeout=10,
    ) as client:
        tasks = [
            make_request(client)
            for _ in range(count)
        ]

        await asyncio.gather(*tasks)

    return {
        "status": "ok",
        "requests_generated": count,
    }


# -------------------------
# Prometheus
# -------------------------

metrics_app = make_asgi_app()

app.mount("/metrics", metrics_app)


# -------------------------
# OpenTelemetry
# -------------------------

FastAPIInstrumentor.instrument_app(app)