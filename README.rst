Prometheus TANGO exporter
=========================

An exporter is a small webserver that publishes metrics data in a text format readable by the Prometheus monitoring service.

This particular exporter inspects the local TANGO "starter" device for any servers that should be running, and monitors those processes for some basic things like CPU and memory usage.

To use it, start "tango_exporter" on the machine where the device servers are running, and point your Prometheus server at port 9110 on that server. Presto!

Dependencies (available on PyPI):
- prometheus_client
- psutil
- PyTango
