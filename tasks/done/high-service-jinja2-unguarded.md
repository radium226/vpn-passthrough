# Jinja2 template rendering unguarded in handle_run_process

**File**: `packages/server/src/radium226/vpn_passthrough/server/service.py`
**Priority**: High

## Problem

`command` and `args` are rendered through Jinja2 on every loop iteration
without catching `jinja2.TemplateError`. A malformed template string (e.g.
`{{ unclosed`) raises an exception that propagates all the way up through the
IPC handler, potentially crashing the connection.

## Fix

Catch `jinja2.TemplateError` and return `CommandNotFound` (or a new error
type) with a descriptive message:

```python
from jinja2 import Template, TemplateError

try:
    command = Template(request.command).render(**jinja_vars)
    args = [Template(arg).render(**jinja_vars) for arg in request.args]
except TemplateError as e:
    logger.error("Jinja2 template error in command: {}", e)
    # close fds and return error
    ...
```
