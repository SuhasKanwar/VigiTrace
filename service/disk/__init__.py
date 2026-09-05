"""On-disk forensic analysis of recorder filesystems.

Separate from ``vendors/``, which reaches a live recorder over the network.
This package works on an acquired image: it opens the file read-only, never
writes to it, and derives everything from the bytes on disk.
"""
