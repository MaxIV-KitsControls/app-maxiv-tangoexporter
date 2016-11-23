#!/usr/bin/env python

"""
An "exporter" that produces data about the TANGO servers running on the
local host. It relies on the tango "Starter" device to list servers and
the python "psutil" module to get metrics about the processes.

There's no configuration, just run this script. The prometheus server,
however needs to be configured to poll it, e.g. "<hostname>:9110".

To check the output, go to http://<hostname>:9110/metrics

TODO:
- configuration (filtering, ..?)
- more server metrics
"""

import socket
import time

from prometheus_client import start_http_server, Gauge
import psutil

import PyTango


# a few globals (sorry about that, just keeping things simple...)
host = socket.gethostname()
db = PyTango.Database()
tango_host = "%s:%s" % (db.get_db_host(), db.get_db_port())


# some helper functions

def get_starter():
    "get the name of the local starter device"
    servers = get_local_servers(host)
    for server in servers:
        if server.startswith("Starter/"):
            devs_clss = db.get_device_class_list(server)
            for dev, cls in zip(devs_clss[::2], devs_clss[1::2]):
                if cls == "Starter":
                    return dev


proxies = {}


def get_proxy(device):
    # just a simple cache of proxies so we don't have to recreate them
    if device in proxies:
        return proxies[device]
    proxy = proxies[device] = PyTango.DeviceProxy(device)
    return proxy


def get_server_process(name):
    "get the process of the given server"
    dserver = "dserver/%s" % name
    try:
        info = db.get_device_info(dserver)
        if info.exported:
            # This indicates that the process has been started
            try:
                # Double check that the server is really running.
                # If the server was not properly stopped (e.g. it crashed)
                # it may not come up as unexported, and a different process
                # might have taken over its PID.
                proxy = get_proxy(dserver)
                proxy.ping()
            except PyTango.DevFailed:
                return
            # Now we are reasonably sure that we're monitoring the right thing
            process = psutil.Process(info.pid)
            process.cpu_percent()  # init the cpu calculation
            return process
    except PyTango.DevFailed:
        return
    except psutil.NoSuchProcess:
        return


def get_local_servers(host):
    "get a dict of servers and their processes"
    return dict((s, get_server_process(s))
                for s in db.get_host_server_list(host))


def get_starter_servers(starter):
    "get the starter's list of controlled servers"
    info = starter.read_attribute("Servers").value
    result = {}
    for line in info:
        server, state, controlled, level = line.split("\t")
        # Filter only servers that are "controlled", e.g. that
        # have a level configured.
        #if controlled == "1":  # This is not always correct!
        if level != "0":  # Let's see if *this* is correct...
            level = int(level)
            ok = state == "ON"
            result[server] = dict(ok=ok, level=level)
    return result


def gather_data(host, period=1):

    "The main loop that publishes metrics forever"

    # define prometheus metrics
    process_metrics = {
        name: Gauge("tango_server_{0}".format(name), desc,
                    ["host", "server", "db"])
        for name, desc in [
                ("running", "TANGO server is running"),
                ("cpu_time_user", "TANGO server process user CPU time"),
                ("cpu_time_system", "TANGO server process system CPU time"),
                ("cpu_percent", "TANGO server process CPU percentage"),
                ("mem_rss", "TANGO server process memory 'resident set size'"),
                ("mem_data", "TANGO server process number_of_threads"),
                ("threads_n", "TANGO server process number_of_threads"),
                ("dserver_ping", "TANGO dserver ping time"),
        ]
    }

    starter_metrics = {
        name: Gauge("tango_server_{0}".format(name), desc,
                    ["host", "server", "db"])
        for name, desc in [
                ("starter_controlled", "TANGO server controlled by starter"),
                ("starter_level", "TANGO server starter run level")
        ]
    }

    # setup a proxy to the local starter
    starter = PyTango.DeviceProxy(get_starter())
    i = 0

    while True:

        if i % 60 == 0:
            # once in a while we check if the starter config has changed
            servers = get_local_servers(host)
            starter_servers = get_starter_servers(starter)
            for server, info in starter_servers.items():
                labels = host, server, tango_host
                starter_metrics["starter_controlled"].labels(*labels).set(True)
                starter_metrics["starter_level"].labels(*labels).set(info["level"])

        i += 1

        # go though all local servers and update the various process metrics
        for server, process in servers.items():

            labels = host, server, tango_host

            if process is None:
                # server is not running
                servers.pop(server)
                # cleanup process metrics
                for metric, gauge in process_metrics.items():
                    if metric == "running" and server in starter_servers:
                        # if the server is still controlled, we keep the
                        # running metric
                        gauge.labels(*labels).set(False)
                        continue
                    try:
                        gauge.remove(*labels)
                    except Exception: # ValueError ?
                        # guess the metric is not yet created, fine
                        pass
                continue

            try:
                # CPU
                cpu_times = process.cpu_times()
                process_metrics["cpu_time_user"].labels(*labels).set(cpu_times.user)
                process_metrics["cpu_time_system"].labels(*labels).set(cpu_times.system)
                process_metrics["cpu_percent"].labels(*labels).set(process.cpu_percent())

                # memory
                mem_info = process.memory_info()
                process_metrics["mem_rss"].labels(*labels).set(mem_info.rss)
                if hasattr(mem_info, "data"):
                    process_metrics["mem_data"].labels(*labels).set(mem_info.data)

                # threads
                process_metrics["threads_n"].labels(*labels).set(process.num_threads())
                try:
                    dserver = "dserver/%s" % server
                    process_metrics["dserver_ping"].labels(*labels).set(get_proxy(dserver).ping())
                    process_metrics["running"].labels(*labels).set(True)
                except PyTango.DevFailed:
                    process_metrics["dserver_ping"].labels(*labels).set(-1)
                    process_metrics["running"].labels(*labels).set(False)

                if server not in starter_servers:
                    starter_metrics["starter_controlled"].labels(*labels).set(False)

            except psutil.NoSuchProcess:
                # looks like the process is gone, let's forget it and
                # let the starter check provide a new one.
                servers.pop(server)
                for gauge in process_metrics.values():
                    try:
                        gauge.remove(*labels)
                    except Exception:
                        pass

        time.sleep(period)


def main():

    PORT_NUMBER = 9110

    # Set a server to export (expose to prometheus) the data
    start_http_server(PORT_NUMBER)

    gather_data(host)


if __name__ == "__main__":
    main()