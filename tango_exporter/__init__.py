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
import threading
import time

from prometheus_client import start_http_server, Gauge
import psutil

import PyTango


# a few globals (sorry about that, just keeping things simple...)
host = socket.gethostname()
db = PyTango.Database()
tango_host = "%s:%s" % (db.get_db_host(), db.get_db_port())
servers = {}
starter_servers = {}


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


def get_server_process(name):
    "get the process of the given server"
    info = db.get_device_info("dserver/%s" % name)
    try:
        process = psutil.Process(info.pid)
        process.cpu_percent()
        return process
    except psutil.NoSuchProcess:
        return


def get_local_servers(host):
    "get a dict of servers and their processes"
    servers = dict((s, get_server_process(s))
                   for s in db.get_host_server_list(host))
    return servers


def get_starter_servers(starter):
    "get the starter's list of controlled servers"
    info = starter.read_attribute("Servers").value
    result = {}
    for line in info:
        server, state, controlled, level = line.split("\t")
        controlled = controlled == "1"
        if controlled:
            level = int(level)
            ok = state == "ON"
            result[server] = dict(ok=ok, level=level)
    return result


def update_servers(host, period=60):
    "periodically update the server info"
    global servers
    global starter_servers
    starter = PyTango.DeviceProxy(get_starter())
    while True:
        servers = get_local_servers(host)
        starter_servers = get_starter_servers(starter)
        time.sleep(period)


def gather_data(host, period=1):

    "The main loop that publishes metrics forever"

    # define prometheus metrics
    server_running = Gauge("tango_server_running", "TANGO server is running",
                           ["host", "server", "db"])
    server_cpu_time_user = Gauge("tango_server_cpu_time_user",
                                 "Tango server process user CPU time",
                                 ["host", "server", "db"])
    server_cpu_time_system = Gauge("tango_server_cpu_time_system",
                                   "TANGO server process system CPU time",
                                   ["host", "server", "db"])
    server_cpu_percent = Gauge("tango_server_cpu_percent",
                               "TANGO server process CPU percentage",
                               ["host", "server", "db"])

    server_mem_rss = Gauge("tango_server_mem_rss",
                           "TANGO server process memory 'resident set size'",
                           ["host", "server", "db"])
    server_mem_data = Gauge("tango_server_mem_data",
                            "TANGO server process memory 'data resident set'",
                            ["host", "server", "db"])

    server_threads_n = Gauge("tango_server_threads_n",
                             "TANGO server process number_of_threads",
                             ["host", "server", "db"])

    server_starter_controlled = Gauge("tango_server_starter_controlled",
                                      "TANGO server controlled by starter",
                                      ["host", "server", "db"])
    server_starter_level = Gauge("tango_server_starter_level",
                                 "TANGO server starter run level",
                                 ["host", "server", "db"])

    while True:
        # go though all local servers and check various metrics
        for server, process in servers.items():
            labels = {"server": server, "host": host, "db": tango_host}
            server_starter_controlled.labels(labels).set(server in starter_servers)

            if process is None:
                # server is not running
                server_running.labels(labels).set(0)
                continue

            if server in starter_servers:
                # add starter info to controlled servers
                server_starter_level.labels(labels).set(starter_servers[server]["level"])

            try:
                # CPU
                cpu_times = process.cpu_times()
                server_cpu_time_user.labels(labels).set(cpu_times.user)
                server_cpu_time_system.labels(labels).set(cpu_times.system)
                cpu_percent = process.cpu_percent()
                server_cpu_percent.labels(labels).set(cpu_percent)

                # memory
                mem_info = process.memory_info()
                server_mem_rss.labels(labels).set(mem_info.rss)
                if hasattr(mem_info, "data"):
                    server_mem_data.labels(labels).set(mem_info.data)

                # threads
                server_threads_n.labels(labels).set(process.num_threads())

                server_running.labels(labels).set(1)

            except psutil.NoSuchProcess:
                # looks like the process is gone, let's forget it and
                # let the update thread provide a new one.
                servers.pop(server)
                server_running.labels(labels).set(0)
                pass

        time.sleep(period)


def main():

    PORT_NUMBER = 9110

    thread = threading.Thread(target=update_servers, args=(host,))
    thread.start()

    # Set a server to export (expose to prometheus) the data
    start_http_server(PORT_NUMBER)

    gather_data(host)


if __name__ == "__main__":
    main()
