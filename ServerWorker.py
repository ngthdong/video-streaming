from random import randint
import sys, traceback, threading, socket

from VideoStream import VideoStream
from RtpPacket import RtpPacket

class ServerWorker:
	SETUP = 'SETUP'
	PLAY = 'PLAY'
	PAUSE = 'PAUSE'
	TEARDOWN = 'TEARDOWN'
	
	INIT = 0
	READY = 1
	PLAYING = 2
	state = INIT
	
	# MTU configuration for UDP fragmentation
	# Ethernet MTU: 1500 bytes
	# IP header: 20 bytes, UDP header: 8 bytes, RTP header: 12 bytes, Frag header: 8 bytes
	# Usable payload: 1500 - 20 - 8 - 12 - 8 = 1452 bytes (use 1400 for safety)
	MTU_PAYLOAD_SIZE = 1400

	OK_200 = 0
	FILE_NOT_FOUND_404 = 1
	CON_ERR_500 = 2
	
	clientInfo = {}
	
	def __init__(self, clientInfo):
		self.clientInfo = clientInfo
		
	def run(self):
		threading.Thread(target=self.recvRtspRequest).start()
	
	def recvRtspRequest(self):
		"""Receive RTSP request from the client."""
		connSocket = self.clientInfo['rtspSocket'][0]
		while True:            
			data = connSocket.recv(256)
			if data:
				print("Data received:\n" + data.decode("utf-8"))
				self.processRtspRequest(data.decode("utf-8"))
	
	def processRtspRequest(self, data):
		"""Process RTSP request sent from the client."""
		# Get the request type
		request = data.split('\n')
		line1 = request[0].split(' ')
		requestType = line1[0]
		
		# Get the media file name
		filename = line1[1]
		
		# Get the RTSP sequence number 
		seq = request[1].split(' ')

		startFrame = 0

		for line in request:
			if line.startswith("Frame"):
				startFrame = int(line.split(" ")[1])
		
		# Process SETUP request
		if requestType == self.SETUP:
			if self.state == self.INIT or self.state == self.READY:
				# Update state
				print("processing SETUP\n")
				
				try:
					if 'videoStream' in self.clientInfo:
						del self.clientInfo['videoStream']
					self.clientInfo['videoStream'] = VideoStream(filename)
					if startFrame > 0:
						self.clientInfo['videoStream'].setFrame(startFrame)
					self.state = self.READY
				except IOError:
					self.replyRtsp(self.FILE_NOT_FOUND_404, seq[1])
				
				# Generate a randomized RTSP session ID
				self.clientInfo['session'] = randint(100000, 999999)
				
				# Send RTSP reply
				self.replyRtsp(self.OK_200, seq[1])
				
				# Get the transport port from the last line (RTP/UDP or RTP/TCP)
				transport = request[2]

				if "UDP" in transport:
					self.clientInfo['transport'] = "UDP"
				else:
					self.clientInfo['transport'] = "TCP"

				self.clientInfo['rtpPort'] = request[2].split(' ')[3]
				# Store client IP for RTP packet sending (critical for remote clients)
				self.clientInfo['clientIP'] = self.clientInfo['rtspSocket'][1][0]

				print(self.clientInfo)
		
		# Process PLAY request 		
		elif requestType == self.PLAY:
			if self.state == self.READY:
				print("processing PLAY\n")
				self.state = self.PLAYING

				self.replyRtsp(self.OK_200, seq[1])

				self.clientInfo['event'] = threading.Event()
				
				if self.clientInfo['transport'] == 'UDP':
					# Create a new socket for RTP/UDP
					self.clientInfo["rtpSocket"] = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
					
					# Create a new thread 
					self.clientInfo['worker']= threading.Thread(target=self.sendRtp) 
				
				else: # TCP 
					port = int(self.clientInfo['rtpPort'])

					self.clientInfo['tcpSocket'] = socket.socket(
						socket.AF_INET,
						socket.SOCK_STREAM
					)

					self.clientInfo['tcpSocket'].setsockopt(
						socket.SOL_SOCKET,
						socket.SO_REUSEADDR,
						1
					)

					self.clientInfo['tcpSocket'].bind(('', port))
					self.clientInfo['tcpSocket'].listen(1)

					print("Waiting for TCP connection...")

					conn, addr = self.clientInfo['tcpSocket'].accept()

					print("TCP connected:", addr)

					self.clientInfo['streamSocket'] = conn

					self.clientInfo['worker'] = threading.Thread(
						target=self.sendTCP
					)
						
				# start sending RTP packets
				self.clientInfo['worker'].start()

		
		# Process PAUSE request
		elif requestType == self.PAUSE:
			if self.state == self.PLAYING:
				print("processing PAUSE\n")
				self.state = self.READY
				
				self.clientInfo['event'].set()
			
				self.replyRtsp(self.OK_200, seq[1])

				if 'tcpSocket' in self.clientInfo:
					self.clientInfo['tcpSocket'].close()

				if 'streamSocket' in self.clientInfo:
					self.clientInfo['streamSocket'].close()

				if 'rtpSocket' in self.clientInfo:
					self.clientInfo['rtpSocket'].close()

		# Process TEARDOWN request
		elif requestType == self.TEARDOWN:
			print("processing TEARDOWN\n")

			self.clientInfo['event'].set()
			
			self.replyRtsp(self.OK_200, seq[1])
			
			# Close the RTP socket
			if 'rtpSocket' in self.clientInfo:
				self.clientInfo['rtpSocket'].close()

			if 'streamSocket' in self.clientInfo:
				self.clientInfo['streamSocket'].close()
			
			if 'tcpSocket' in self.clientInfo:
					self.clientInfo['tcpSocket'].close()
			
	def sendRtp(self):
		"""Send RTP packets over UDP."""
		while True:
			self.clientInfo['event'].wait(0.05) 
			
			# Stop sending if request is PAUSE or TEARDOWN
			if self.clientInfo['event'].is_set(): 
				break 
				
			data = self.clientInfo['videoStream'].nextFrame()
			if data: 
				frameNumber = self.clientInfo['videoStream'].frameNbr()
				try:
					address = self.clientInfo['clientIP']  # Use stored client IP for remote connections
					port = int(self.clientInfo['rtpPort'])
					
					# Check if frame needs fragmentation
					if len(data) > self.MTU_PAYLOAD_SIZE:
						# Fragment the frame
						fragments = self.fragmentFrame(data, frameNumber)
						for fragment in fragments:
							self.clientInfo['rtpSocket'].sendto(fragment, (address, port))
					else:
						# Send as single packet without fragmentation
						self.clientInfo['rtpSocket'].sendto(self.makeRtp(data, frameNumber), (address, port))
				except:
					print("Connection Error")

			else: print('No data')

	def sendTCP(self):
		streamSocket = self.clientInfo['streamSocket']

		while True:
			self.clientInfo['event'].wait(0.05)

			if self.clientInfo['event'].is_set():
				break

			data = self.clientInfo['videoStream'].nextFrame()

			if data:
				frameNumber = self.clientInfo['videoStream'].frameNbr()

				try:
					rtpPacket = self.makeRtp(data, frameNumber)

					length = len(rtpPacket).to_bytes(4, 'big')

					streamSocket.sendall(length + rtpPacket)

					import time
					time.sleep(0.04)

				except:
					print("TCP streaming error")
					try:
						streamSocket.close()
					except:
						pass
					break
			else: print('No data')

	def makeRtp(self, payload, frameNbr):
		"""RTP-packetize the video data."""
		version = 2
		padding = 0
		extension = 0
		cc = 0
		marker = 0
		pt = 26 # MJPEG type
		seqnum = frameNbr
		ssrc = 0 
		
		rtpPacket = RtpPacket()
		
		rtpPacket.encode(version, padding, extension, cc, seqnum, marker, pt, ssrc, payload)
		
		return rtpPacket.getPacket()

	def fragmentFrame(self, frameData, frameNbr):
		"""Fragment a frame into multiple UDP packets if it exceeds MTU.
		
		Returns a list of RTP packets with fragmentation headers.
		"""
		fragments = []
		frameSize = len(frameData)
		
		# Calculate number of fragments needed
		numFragments = (frameSize + self.MTU_PAYLOAD_SIZE - 1) // self.MTU_PAYLOAD_SIZE
		
		version = 2
		padding = 0
		extension = 0
		cc = 0
		marker = 0
		pt = 26  # MJPEG type
		seqnum = frameNbr
		ssrc = 0
		
		# Create fragments
		for fragIndex in range(numFragments):
			startIdx = fragIndex * self.MTU_PAYLOAD_SIZE
			endIdx = min(startIdx + self.MTU_PAYLOAD_SIZE, frameSize)
			payload = frameData[startIdx:endIdx]
			
			# Create fragmentation info
			fragInfo = {
				'frame_id': frameNbr,
				'fragment_index': fragIndex,
				'total_fragments': numFragments
			}
			
			rtpPacket = RtpPacket()
			rtpPacket.encode(version, padding, extension, cc, seqnum + fragIndex, 
						   marker, pt, ssrc, payload, fragmentation_info=fragInfo)
			
			fragments.append(rtpPacket.getPacket())
		
		return fragments

	def replyRtsp(self, code, seq):
		"""Send RTSP reply to the client."""
		if code == self.OK_200:
			#print("200 OK")
			reply = 'RTSP/1.0 200 OK\nCSeq: ' + seq + '\nSession: ' + str(self.clientInfo['session'])
			connSocket = self.clientInfo['rtspSocket'][0]
			connSocket.send(reply.encode())
		
		# Error messages
		elif code == self.FILE_NOT_FOUND_404:
			print("404 NOT FOUND")
		elif code == self.CON_ERR_500:
			print("500 CONNECTION ERROR")

