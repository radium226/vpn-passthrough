from .network_namespace import NetworkNamespace


def executable(capture_output: bool = True):
    def decorator(func):
        def closure(*args, network_namespace: NetworkNamespace | None = None, **kwargs):
            return network_namespace.attach(func, capture_output)(*args, **kwargs) if network_namespace else func(*args, **kwargs)
        return closure
    return decorator