"""沙箱层：OpenSandbox 适配器（本地 dev 连 docker，prod 连云端）。"""

from src.sandbox.adapter import DEFAULT_IMAGE, OpenSandboxAdapter

__all__ = ["DEFAULT_IMAGE", "OpenSandboxAdapter"]
