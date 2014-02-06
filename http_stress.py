# CC3000 HTTP Server Stress Test

# Generate a configurable amount of HTTP load against a CC3000 server.
# The load is made up of clients which connect and read all the received
# data until the server closes the connection.

# Specify a number of threads to use and target connection requests per second (RPS) 
# in the configuration below to run.

import socket
import time
import threading

# CONFIGURATION:

# CC3000 server IP and port:
SERVER_IP = '192.168.1.135'
SERVER_PORT = 80

# High load configuration:
# TARGET_THREAD_COUNT = 30
# TARGET_CONNECT_RPS = 30.0
# SOCKET_TIMEOUT_SECONDS = 0.5

# Low load configuration
TARGET_THREAD_COUNT = 8
TARGET_CONNECT_RPS = 4.0
SOCKET_TIMEOUT_SECONDS = 0.1

# Longer timeout consistently locks up:
# SOCKET_TIMEOUT_SECONDS = 1.0

RUNTIME_SECONDS = 30


# Thread-safe performance counter that allows measuring events per second.
class PerfCounter(object):
	def __init__(self, window_seconds=2):
		self.window_seconds = window_seconds
		self.lock = threading.Lock()
		self.log = {}
		self.total = 0

	def count(self):
		# Count an event at the current time.
		count_time = int(time.time())
		with self.lock:
			self.log[count_time] = self.log.get(count_time, 0) + 1
			self.total += 1

	def average_rps(self):
		# Calculate the average RPS over the last window of time.
		target_time = int(time.time())
		total = 0
		new_log = {}
		with self.lock:
			for i in range(target_time-self.window_seconds, target_time+1):
				value = self.log.get(i, 0)
				total += value
				new_log[i] = value
			# Drop old measurements that won't be used anymore.
			self.log = new_log
		return total / (self.window_seconds+1.0)


# Function that connects to the server and sends an HTTP request.
# All response data is read until the server closes the connection.
def handle_connection(ip, port, stop_event, counters):
	soc = None
	try:
		soc = socket.socket(socket.AF_INET, socket.SOCK_STREAM);
		counters['connect'].count()
		try:
			soc.connect((ip, port))
		except socket.timeout:
			counters['connect_timeout'].count()
			return
		#soc.sendall('GET /foo HTTP/1.1\r\n\r\n')
		soc.sendall('GET / HTTP/1.1\r\n')
		soc.sendall('Host: 192.168.1.135\r\n')
		soc.sendall('Connection: keep-alive\r\n')
		soc.sendall('Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8\r\n')
		soc.sendall('User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/32.0.1700.107 Safari/537.36\r\n')
		soc.sendall('Accept-Encoding: gzip,deflate,sdch\r\n')
		soc.sendall('Accept-Language: en-US,en;q=0.8\r\n')
		soc.sendall('\r\n')
		while not stop_event.is_set():
			data = soc.recv(1024)
			if not data:
				counters['finished'].count()
				return
	except socket.error:
		# Something went wrong with the socket, log it and stop.
		counters['socket_error'].count()
		return
	finally:
		if soc is not None:
			soc.close()


# Code that each thread will execute.  Continually connects to the server
# every delay + offset seconds in an attempt to hit a target connect RPS.
def process_connection(ip, port, delay, offset, start_event, stop_event, counters):
	# Don't start until you get the signal from the event.
	start_event.wait()
	# Delay for the instructed period of time before starting.
	if offset > 0:
		time.sleep(offset)
	while not stop_event.is_set():
		# Send a request and retrieve all the data.
		connect_time = time.time()
		handle_connection(ip, port, stop_event, counters)
		# Wait until it's time to send another request.
		sleep_time = (delay + offset) - (time.time() - connect_time)
		if sleep_time > 0:
			time.sleep(sleep_time)


# How long each thread should wait before sending a request.
thread_delay = 1.0 / (TARGET_CONNECT_RPS / TARGET_THREAD_COUNT)
# Offset each thread should wait before starting to send requests
# so requests don't happen all at once.
thread_offset = 1.0 / TARGET_THREAD_COUNT

print '# Threads:', TARGET_THREAD_COUNT
print 'RPS Target:', TARGET_CONNECT_RPS
print 'Thread delay:', thread_delay
print 'Thread_offset:', thread_offset

# Event to signal when each thread should start.
start_event = threading.Event()
# Event to signal the threads should stop.
stop_event = threading.Event()
# Set default timeout for sockets.
socket.setdefaulttimeout(SOCKET_TIMEOUT_SECONDS)

# Perf counters to measure connections and errors per second.
counters = {}
counters['connect'] = PerfCounter()
counters['connect_timeout'] = PerfCounter()
counters['socket_error'] = PerfCounter()
counters['finished'] = PerfCounter()

# Create and start all the required threads.
threads = []
for i in range(TARGET_THREAD_COUNT):
	thread = threading.Thread(target=process_connection, args=(SERVER_IP, 
															   SERVER_PORT, 
															   thread_delay, 
															   thread_offset * i, 
															   start_event, 
															   stop_event,
															   counters))
	thread.start()

# Fire the start event so threads send load.
print 'Starting load!'
start_event.set()
start = time.time()
try:
	# Periodically display stats from perf counters.
	for i in range(RUNTIME_SECONDS):
		time.sleep(1.0)
		print 'Connect RPS: {:0.2f}\tConnect Timeout RPS: {:0.2f}\tSocket Error RPS: {:0.2f}\t\tFinished RPS: {:0.2f}'.format(
				counters['connect'].average_rps(), 
				counters['connect_timeout'].average_rps(),
				counters['socket_error'].average_rps(),
				counters['finished'].average_rps())
except KeyboardInterrupt:
	pass
finally:
	# Fire the stop event to stop all the threads.
	print 'Stopping load!'
	stop_event.set()
	# Wait for the threads to finish.
	for thread in threads:
		thread.join()
	# Print some details on the runtime.
	print 'Ran for {:0.2f} seconds'.format(time.time() - start)
	connects = float(counters['connect'].total)
	print 'Total connects:\t\t\t{:0.0f}'.format(connects)
	connect_timeouts = float(counters['connect_timeout'].total)
	print 'Total connect timeouts:\t\t{:0.0f}\t{:0.2f}% of connects'.format(connect_timeouts, connect_timeouts / connects * 100.0) 
	socket_errors = float(counters['socket_error'].total)
	print 'Total socket errors:\t\t{:0.0f}\t{:0.2f}% of connects'.format(socket_errors, socket_errors / connects * 100.0)
	finished = float(counters['finished'].total)
	print 'Total finished:\t\t\t{:0.0f}\t{:0.2f}% of connects'.format(finished, finished / connects * 100.0)
	print 'Requests accounted for:\t\t{:0.2f}%'.format((connect_timeouts + socket_errors + finished)/ connects * 100.0)
