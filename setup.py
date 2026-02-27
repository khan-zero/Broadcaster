from setuptools import setup, find_packages

setup(
    name="auto-sender",
    version="1.1",
    packages=find_packages(),
    install_requires=[
        "customtkinter",
        "telethon",
        "pillow",
        "python-dotenv",
        "requests",
    ],
    entry_points={
        "console_scripts": [
            "auto-sender=main:main",
        ],
    },
)
