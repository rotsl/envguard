"""Simple demo application."""
import requests
import numpy as np
import click


@click.command()
def main():
    click.echo("Hello from pip-simple-demo!")
    click.echo(f"NumPy version: {np.__version__}")
    click.echo(f"Requests version: {requests.__version__}")


if __name__ == "__main__":
    main()
