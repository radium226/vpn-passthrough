from click import command


@command()
def app() -> None:
    """Run the VPN passthrough application."""
    print("VPN Passthrough Application is running...")
