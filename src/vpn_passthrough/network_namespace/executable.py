from .network_namespace import NetworkNamespace


def executable(func):
    def closure(*args, network_namespace: NetworkNamespace | None = None, **kwargs):
        return network_namespace.attach(func)(*args, **kwargs) if network_namespace else func(*args, **kwargs)
    return closure