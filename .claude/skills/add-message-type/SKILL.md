---
name: add-message-type
description: Add a new IPC message type to the vpn-passthrough system. Use this skill whenever the user wants to add a new request, response, or event type — even if they just say "add a new command", "add a new operation", or "I need the daemon to support X".
---

# Add a New Message Type

Adding a new message type requires changes across three packages in strict dependency order:
1. `packages/messages` — Define the Pydantic models and update the codec
2. `packages/server` — Add the request handler in the daemon
3. `packages/client` — Expose a high-level method on the `Client` class

Read the existing code before writing anything.

---

## Step 1 — packages/messages

**File:** `packages/messages/src/radium226/vpn_passthrough/messages/__init__.py`

### 1a. Define the Pydantic models

**Response model** — must have `request_id: str` (implements the `Response` structural protocol):
```python
class MyResponse(BaseModel):
    request_id: str
    some_field: SomeType
    type: Literal["my_response"] = "my_response"
```

**Event model** — no `request_id` required:
```python
class MyEvent(BaseModel):
    some_field: SomeType
    type: Literal["my_event"] = "my_event"
```

**Request model** — inherits from both `BaseModel` and `Request[ResponseT, EventT]`. Use `Never` for `EventT` if there are no events:
```python
class MyRequest(BaseModel, Request[MyResponse, MyEvent]):
    id: str
    some_param: SomeType
    type: Literal["my_request"] = "my_request"
```

### 1b. Update the type aliases

Add the new types to `_Response` and `_Event`:
```python
type _Response = Annotated[ProcessTerminated | CommandNotFound | ProcessKilled | MyResponse, Discriminator("type")]
type _Event = ProcessStarted | ProcessRestarted | MyEvent
```

### 1c. Update `_TYPE_ADAPTER`

Add all new classes to the discriminated union:
```python
_TYPE_ADAPTER = TypeAdapter(
    Annotated[
        RunProcess | KillProcess | MyRequest | ... | MyEvent | ... | MyResponse,
        Discriminator("type"),
    ]
)
```

### 1d. Update `_encode` and `_decode` signatures

Widen the union to include the new request type:
```python
def _encode(message: RunProcess | KillProcess | MyRequest | _Event | _Response) -> bytes: ...
def _decode(data: bytes) -> RunProcess | KillProcess | MyRequest | _Event | _Response: ...
```

### 1e. Update `CODEC`

Widen all three type parameters:
```python
CODEC = Codec[
    RunProcess | KillProcess | MyRequest,
    ProcessStarted | ProcessRestarted | MyEvent,
    ProcessTerminated | CommandNotFound | ProcessKilled | MyResponse,
](encode=_encode, decode=_decode)
```

---

## Step 2 — packages/server

**File:** `packages/server/src/radium226/vpn_passthrough/server/daemon.py`

### 2a. Import the new types

Add the new models to the import from `radium226.vpn_passthrough.messages`.

### 2b. Write the handler function

```python
async def handle_my_request(
    request: MyRequest,
    fds: list[int],
    emit: Emit[MyEvent],   # use Emit[Never] if no events
) -> tuple[MyResponse, list[int]]:
    # Call await emit(MyEvent(...), []) to stream events before returning.
    return MyResponse(request_id=request.id, some_field=value), []
```

- Call `await emit(event, [])` to send events before the final response.
- Return `(response, fds_to_pass_back)` — use `[]` for fds unless returning file descriptors.

### 2c. Register in `daemon()`

```python
async with open_server(socket_file_path, CODEC, handlers=[
    ...,
    RequestHandler(request_type=MyRequest, on_request=handle_my_request),
]) as server:
```

---

## Step 3 — packages/client

**File:** `packages/client/src/radium226/vpn_passthrough/client/client.py`

### 3a. Import the new types

Add the new models to the import from `radium226.vpn_passthrough.messages`.

### 3b. Add a method to `Client`

```python
async def my_operation(self, some_param: SomeType) -> ResultType:
    loop = asyncio.get_running_loop()
    result_future: asyncio.Future[ResultType] = loop.create_future()

    async def on_event(event: MyEvent, fds: list[int]) -> None:
        pass  # handle streaming events if needed

    async def on_response(response: MyResponse, fds: list[int]) -> None:
        result_future.set_result(response.some_field)

    await self.ipc.request(
        MyRequest(id=str(uuid.uuid4()), some_param=some_param),
        handler=ResponseHandler[MyEvent, MyResponse](
            on_event=on_event,
            on_response=on_response,
        ),
        fds=[],
    )

    return await result_future
```

- Use `asyncio.Future` to bridge the callback into an awaitable return value.
- If no events, omit `on_event` and use `ResponseHandler[Never, MyResponse]`.
- Pass file descriptors via `fds=` when the operation needs them (e.g. stdin/stdout/stderr).

---

## Validation

After each package change, run from inside that package directory:

```bash
uv run ty check    # catch type errors
uv run ruff check  # catch lint issues
```

Full suite from `packages/client`:
```bash
mise run check
```
