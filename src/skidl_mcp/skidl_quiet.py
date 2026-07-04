"""Suppress SKiDL's working-directory file artifacts.

Importing ``skidl`` immediately attaches file handlers that create
``<script>.log`` and ``<script>.erc`` in the current directory.  The MCP
server's CWD is whatever project the user has open, so those files are
litter in someone else's repo.

Import this module before (or instead of) importing ``skidl``: it triggers
the skidl import itself, then removes the file handlers — which also deletes
the just-created files.  Errors and warnings still reach stderr, which is
where an MCP stdio server wants them.

Netlist backup libraries (``<script>_lib_sklib.py``) are a separate artifact,
suppressed at the call site with ``generate_netlist(do_backup=False)``.
"""

from skidl.logger import stop_log_file_output

stop_log_file_output()
