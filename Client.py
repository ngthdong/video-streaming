from tkinter import *
import tkinter.messagebox as tkMessageBox
from PIL import Image, ImageTk
import socket, threading, sys, traceback, os, time

from RtpPacket import RtpPacket
from Utils import Utils 

from collections import deque

CACHE_DIR = "cache"
CACHE_FILE_NAME = "cache-"
CACHE_FILE_EXT = ".jpg"

class Client:
	INIT = 0
	READY = 1
	PLAYING = 2
	state = INIT
	
	SETUP = 0
	PLAY = 1
	PAUSE = 2
	TEARDOWN = 3
	
	# Initiation..
	def __init__(self, master, serveraddr, serverport, rtpport, filename):
		self.master = master
		self.master.protocol("WM_DELETE_WINDOW", self.handler)
		self.createWidgets()
		self.serverAddr = serveraddr
		self.serverPort = int(serverport)
		self.rtpPort = int(rtpport)
		self.fileName = filename
		self.rtspSeq = 0
		self.sessionId = 0
		self.requestSent = -1
		self.teardownAcked = 0
		self.connectToServer()
		self.frameNbr = 0

		self.currentTime = 0

		self.totalFrames = Utils.get_total_frame_mjpeg(filename)

		self.transportMode = 'UDP' if 'sd' in filename else "TCP"

		self.rtspRunning = True

		self.buffer = deque()
		self.BUFFER_SIZE = 100     # max frame trong buffer
		self.PREBUFFER = 50         # frame numbers need to play 
		self.bufferLock = threading.Lock()
		
		# Fragment reassembly buffers for UDP
		# Structure: {frame_id: {'timestamp': arrival_time, 'fragments': {frag_index: data}}}
		self.fragmentBuffer = {}  # {frame_id: {'timestamp': float, 'fragments': {frag_index: data}}}
		self.fragmentLock = threading.Lock()
		self.FRAGMENT_TIMEOUT_MS = 100  # timeout in milliseconds for incomplete fragments

		if not os.path.exists(CACHE_DIR):
			os.makedirs(CACHE_DIR)
				
		# Add event for synchronization during quality switch
		self.setupEvent = threading.Event()
		self.setupEvent.clear() 
		
	def createWidgets(self):
		"""Build GUI."""
		# Create Setup button
		self.setup = Button(self.master, width=20, padx=3, pady=3)
		self.setup["text"] = "Setup"
		self.setup["command"] = self.setupMovie
		self.setup.grid(row=1, column=0, padx=2, pady=2, sticky="w")
		
		# Create Play button		
		self.start = Button(self.master, width=20, padx=3, pady=3)
		self.start["text"] = "Play"
		self.start["command"] = self.playMovie
		self.start.grid(row=1, column=1, padx=2, pady=2, sticky="w")
		
		# Create Pause button			
		self.pause = Button(self.master, width=20, padx=3, pady=3)
		self.pause["text"] = "Pause"
		self.pause["command"] = self.pauseMovie
		self.pause.grid(row=1, column=2, padx=2, pady=2, sticky="w")
		
		# Create Teardown button
		self.teardown = Button(self.master, width=20, padx=3, pady=3)
		self.teardown["text"] = "Teardown"
		self.teardown["command"] =  self.exitClient
		self.teardown.grid(row=1, column=3, padx=2, pady=2, sticky="w")

		self.quality_sd = Button(self.master, width=10, padx=3, pady=3)
		self.quality_sd["text"] = "sd"
		self.quality_sd["command"] =  lambda: self.transportVideo("SD")
		self.quality_sd.grid(row=2, column=1, padx=2, pady=2, sticky="w")

		self.quality_720p = Button(self.master, width=10, padx=3, pady=3)
		self.quality_720p["text"] = "720p"
		self.quality_720p["command"] =  lambda: self.transportVideo("720P")
		self.quality_720p.grid(row=2, column=2, padx=2, pady=2, sticky="w")

		self.quality_1080p = Button(self.master, width=10, padx=3, pady=3)
		self.quality_1080p["text"] = "1080p"
		self.quality_1080p["command"] =  lambda: self.transportVideo("1080P")
		self.quality_1080p.grid(row=2, column=3, padx=2, pady=2, sticky="w")
		
		# Create a label to display the movie
		self.label = Label(self.master, height=19)
		self.label.grid(row=0, column=0, columnspan=4, sticky=W+E+N+S, padx=5, pady=5) 

		# Create time overlay
		self.timeLabel = Label(
			self.label,
			text="00:00",
			fg="white",
			font=("Helvetica", 12, "bold")
		)
		self.timeLabel.place(relx=0.07, rely=0.97, anchor="se")

		# Create progress bar background
		self.progressBg = Canvas(
			self.label,
			height=6,
			bg="black",
			highlightthickness=0
		)
		self.progressBg.place(relx=0, rely=1.0, relwidth=1.0, anchor="sw")

		# BUFFER BAR (gray)
		self.bufferBar = Canvas(
			self.progressBg,
			height=6,
			bg="gray",
			highlightthickness=0,
			width=1
		)
		self.bufferBar.place(x=0, y=0)

		# PLAY PROGRESS (red)
		self.progressBar = Canvas(
			self.progressBg,
			height=6,
			bg="red",
			highlightthickness=0,
			width=1
		)

		self.loadingLabel = Label(
			self.label,
			text="Loading...",
			fg="white",
			bg="black",
			font=("Helvetica", 16, "bold")
		)

		self.progressBar.place(x=0, y=0)

	def updateTime(self):
		self.currentTime += 1
		# minutes, seconds = Utils.format_time_mmss(self.currentTime)
		minutes, seconds = self.frameNbr // 60, self.currentTime % 60
		self.timeLabel.config(text=f"{minutes:02d}:{seconds:02d}")

		# Call back after 1s
		self.master.after(1000, self.updateTime)

	def updateProgress(self):
		progress = self.frameNbr / self.totalFrames
		barWidth = int(self.label.winfo_width() * progress)

		self.progressBar.config(width=barWidth)

	def updateBufferBar(self):
		with self.bufferLock:
			bufferedFrames = len(self.buffer)

		bufferedPosition = self.frameNbr + bufferedFrames
		progress = bufferedPosition / self.totalFrames
		barWidth = int(self.label.winfo_width() * progress)
		self.bufferBar.config(width=barWidth)

	def showLoading(self):
		self.loadingLabel.place(relx=0.5, rely=0.5, anchor="center")

	def hideLoading(self):
		self.loadingLabel.place_forget()

	def _cleanupTimedOutFragments(self):
		"""Remove incomplete frames from fragmentBuffer if timeout exceeded.
		This method should be called with fragmentLock held."""
		current_time = time.time()
		timeout_seconds = self.FRAGMENT_TIMEOUT_MS / 1000.0
		
		# Collect frame IDs to remove (to avoid modifying dict during iteration)
		frames_to_remove = []
		
		for frameId, frame_data in self.fragmentBuffer.items():
			timestamp = frame_data['timestamp']
			elapsed_time = current_time - timestamp
			
			# If timeout exceeded, mark for removal
			if elapsed_time > timeout_seconds:
				frames_to_remove.append(frameId)
		
		# Remove timed-out frames and log
		for frameId in frames_to_remove:
			del self.fragmentBuffer[frameId]
			print(f"Removed incomplete frame {frameId} (timeout: {self.FRAGMENT_TIMEOUT_MS}ms)")
	
	def setupMovie(self):
		"""Setup button handler."""
		if self.state == self.INIT:
			self.sendRtspRequest(self.SETUP)
	
	def exitClient(self):
		"""Teardown button handler."""
		self.sendRtspRequest(self.TEARDOWN)		
		self.master.destroy() # Close the gui window
		cachename = os.path.join(
			CACHE_DIR,
			CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT
		) # Delete the cache image from video
		if os.path.exists(cachename):
			os.remove(cachename)

		self.timeLabel.config(text="00:00")

	def pauseMovie(self):
		"""Pause button handler."""
		if self.state == self.PLAYING:
			self.sendRtspRequest(self.PAUSE)

	def playMovie(self):
		"""Play button handler."""
		if self.state == self.READY:
			# Create a new thread to listen for RTP packets
			self.sendRtspRequest(self.PLAY)

			if self.transportMode == "TCP":
				self.openRtpPort()

			threading.Thread(target=self.listenRtp).start()

			self.playEvent = threading.Event()
			self.playEvent.clear()

			threading.Thread(target=self.playFromBuffer).start()
			self.updateTime()

	def playFromBuffer(self):
		import time

		# Initial buffering
		self.showLoading()
		while len(self.buffer) < self.PREBUFFER:
			time.sleep(0.01)

		self.hideLoading()
		print("Buffer ready, start playback")

		while True:

			if self.playEvent.is_set():
				break

			with self.bufferLock:
				buffer_len = len(self.buffer)

			# BUFFER EMPTY → PAUSE PLAYBACK
			if buffer_len == 0:
				print("Buffer underrun... waiting")

				self.showLoading()

				# wait until buffer refilled
				while len(self.buffer) < self.PREBUFFER:
					time.sleep(0.01)

				print("Buffer refilled")

				self.hideLoading()

			with self.bufferLock:
				frameNbr, payload = self.buffer.popleft()

			self.frameNbr = frameNbr

			self.updateProgress()
			self.updateBufferBar()

			self.updateMovie(self.writeFrame(payload))

			time.sleep(0.04)
	
	def listenRtp(self):
		"""Listen for RTP packets."""
		while True:
			try:
				if self.transportMode == 'UDP':
					data = self.rtpSocket.recv(20480)

					if data:
						rtpPacket = RtpPacket()
						
						# Try decoding with fragmentation support
						rtpPacket.decode_with_fragmentation(data)
						
						fragInfo = rtpPacket.getFragmentationInfo()
						
						if fragInfo:
							# This is a fragmented packet
							frameId = fragInfo['frame_id']
							fragIndex = fragInfo['fragment_index']
							totalFrags = fragInfo['total_fragments']
							payload = rtpPacket.getPayload()
							
							with self.fragmentLock:
								# Periodically clean up timed-out frames
								self._cleanupTimedOutFragments()
								
								# Initialize fragment buffer for this frame if needed
								if frameId not in self.fragmentBuffer:
									self.fragmentBuffer[frameId] = {
										'timestamp': time.time(),
										'fragments': {}
									}
								
								# Store this fragment
								self.fragmentBuffer[frameId]['fragments'][fragIndex] = payload
								
								# Check if we have all fragments
								if len(self.fragmentBuffer[frameId]['fragments']) == totalFrags:
									# Reassemble the frame
									completeFrame = b''
									for i in range(totalFrags):
										completeFrame += self.fragmentBuffer[frameId]['fragments'][i]
									
									# Clean up
									del self.fragmentBuffer[frameId]
									
									self.updateProgress()
		
									print(f"Frame reassembled: {frameId} ({totalFrags} fragments)")
									
									with self.bufferLock:
										if len(self.buffer) < self.BUFFER_SIZE:
											self.buffer.append((frameId, completeFrame))
									
									self.updateBufferBar()
						else:
							# Non-fragmented packet
							currFrameNbr = rtpPacket.seqNum()
							self.updateProgress()

							print("Current Seq Num:", currFrameNbr)

							payload = rtpPacket.getPayload()

							with self.bufferLock:
								if len(self.buffer) < self.BUFFER_SIZE:
									self.buffer.append((currFrameNbr, payload))
							
							self.updateBufferBar()

				else:  # TCP
					header = self.rtpSocket.recv(4)

					if not header:
						break

					frame_len = int.from_bytes(header, "big")

					data = b''
					while len(data) < frame_len:
						packet = self.rtpSocket.recv(frame_len - len(data))

						if not packet:
							break

						data += packet

					if data:

						rtpPacket = RtpPacket()
						rtpPacket.decode(data)

						currFrameNbr = rtpPacket.seqNum()

						self.updateProgress()

						print("Current Seq Num:", currFrameNbr)

						payload = rtpPacket.getPayload()

						with self.bufferLock:
							if len(self.buffer) < self.BUFFER_SIZE:
								self.buffer.append((currFrameNbr, payload))
						
						self.updateBufferBar()

			except:
				# Pause
				if self.playEvent.isSet():
					break

				# Teardown
				if self.teardownAcked == 1:
					try:
						self.rtpSocket.shutdown(socket.SHUT_RDWR)
					except:
						pass

					self.rtpSocket.close()
					break
				
					
	def writeFrame(self, data):
		"""Write the received frame to a temp image file. Return the image file."""
		cachename = os.path.join(
			CACHE_DIR,
			CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT
		)
		file = open(cachename, "wb")
		file.write(data)
		file.close()
		
		return cachename
	
	def updateMovie(self, imageFile):
		"""Update the image file as video frame in the GUI."""
		photo = ImageTk.PhotoImage(Image.open(imageFile))
		self.label.configure(image = photo, height=288) 
		self.label.image = photo
		
	def connectToServer(self):
		"""Connect to the Server. Start a new RTSP/TCP session."""
		# Close old socket if it exists
		try:
			if hasattr(self, 'rtspSocket') and self.rtspSocket:
				self.rtspSocket.close()
		except:
			pass
		
		# Reset session ID for new connection
		self.sessionId = 0
		
		self.rtspSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		try:
			self.rtspSocket.connect((self.serverAddr, self.serverPort))
		except:
			tkMessageBox.showwarning('Connection Failed', 'Connection to \'%s\' failed.' %self.serverAddr)
	
	def sendRtspRequest(self, requestCode):
		"""Send RTSP request to the server."""
		request = ""

		# Setup request
		if requestCode == self.SETUP and self.state == self.INIT:
			threading.Thread(target=self.recvRtspReply).start()
			self.rtspSeq += 1
			request = f"SETUP {self.fileName} RTSP/1.0\n" \
					f"CSeq: {self.rtspSeq}\n" \
					f"Transport: RTP/{self.transportMode}; client_port= {self.rtpPort}\n" \
					f"Frame: {self.frameNbr}"
			
			self.requestSent = self.SETUP

		# Play request
		elif requestCode == self.PLAY and self.state == self.READY:
			self.rtspSeq += 1
			request = f"PLAY {self.fileName} RTSP/1.0\n" \
					f"CSeq: {self.rtspSeq}\n" \
					f"Session: {self.sessionId}"
			self.requestSent = self.PLAY

		# Pause request
		elif requestCode == self.PAUSE and self.state == self.PLAYING:
			self.rtspSeq += 1
			request = f"PAUSE {self.fileName} RTSP/1.0\n" \
					f"CSeq: {self.rtspSeq}\n" \
					f"Session: {self.sessionId}"
			self.requestSent = self.PAUSE

		# Teardown request
		elif requestCode == self.TEARDOWN and self.state != self.INIT:
			self.rtspSeq += 1
			request = f"TEARDOWN {self.fileName} RTSP/1.0\n" \
					f"CSeq: {self.rtspSeq}\n" \
					f"Session: {self.sessionId}"
			self.requestSent = self.TEARDOWN
		else:
			return

		self.rtspSocket.send(request.encode())
		print("\nData sent:\n" + request)

		
	def recvRtspReply(self):
		"""Receive RTSP reply from the server."""
		while True:
			reply = self.rtspSocket.recv(1024)
			
			if reply: 
				self.parseRtspReply(reply.decode("utf-8"))
			
			# Close the RTSP socket upon requesting Teardown
			if self.requestSent == self.TEARDOWN:
				self.rtspSocket.shutdown(socket.SHUT_RDWR)
				self.rtspSocket.close()
				break
	
	def parseRtspReply(self, data):
		"""Parse the RTSP reply from the server."""
		lines = data.split('\n')
		seqNum = int(lines[1].split(' ')[1])
		
		# Process only if the server reply's sequence number is the same as the request's
		if seqNum == self.rtspSeq:
			session = int(lines[2].split(' ')[1])
			# New RTSP session ID
			if self.sessionId == 0:
				self.sessionId = session
			
			# Process only if the session ID is the same
			if self.sessionId == session:
				if int(lines[0].split(' ')[1]) == 200: 

					if self.requestSent == self.SETUP:
						self.state = self.READY
						if self.transportMode == 'UDP':
							self.openRtpPort()
						self.setupEvent.set()  # Signal that SETUP is complete 

					elif self.requestSent == self.PLAY:
						self.state = self.PLAYING
					
					elif self.requestSent == self.PAUSE:
						self.state = self.READY
						
						# The play thread exits. A new thread is created on resume.
						self.playEvent.set()
					elif self.requestSent == self.TEARDOWN:
						self.state = self.INIT
						
						# Flag the teardownAcked to close the socket.
						self.teardownAcked = 1 
	
	def openRtpPort(self):
		"""Open RTP socket binded to a specified port."""
		# Close old RTP socket if it exists
		try:
			if hasattr(self, 'rtpSocket') and self.rtpSocket:
				self.rtpSocket.close()
		except:
			pass
		
		if self.transportMode == 'UDP':
			self.rtpSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
			# Set SO_REUSEADDR to allow quick rebinding
			self.rtpSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
		
			try:
				self.rtpSocket.bind(('', self.rtpPort))
			except Exception as e:
				tkMessageBox.showwarning('Unable to Bind', f'Unable to bind PORT={self.rtpPort}\nError: {str(e)}')
				raise
		
		else: # TCP
			import time

			self.rtpSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

			print("Connecting TCP stream...")

			for i in range(10):
				try:
					self.rtpSocket.connect((self.serverAddr, self.rtpPort))
					print("TCP connected")
					break
				except:
					print("Retry TCP connect...")
					time.sleep(0.2)
	def handler(self):
		"""Handler on explicitly closing the GUI window."""
		self.pauseMovie()
		if tkMessageBox.askokcancel("Quit?", "Are you sure you want to quit?"):
			self.exitClient()
		else: # When the user presses cancel, resume playing.
			self.playMovie()

	def transportVideo(self, quality):
		# stop RTP thread
		if self.state == self.PLAYING:
			self.pauseMovie()
		
		# Always clear buffers for quality switch
		with self.bufferLock:
			self.buffer.clear()
		
		with self.fragmentLock:
			self.fragmentBuffer.clear()

		if quality == "SD":
			self.transportMode = "UDP"
			self.fileName = "videos/sd.Mjpeg"

		elif quality == "720P":
			self.transportMode = "TCP"
			self.fileName = "videos/720p.Mjpeg"

		elif quality == "1080P":
			self.transportMode = "TCP"
			self.fileName = "videos/1080p.Mjpeg"

		print("Switch quality:", quality)

		# Keep current frameNbr for continuity, reset only progress tracking
		# self.frameNbr stays the same - server will seek to this frame
		self.totalFrames = Utils.get_total_frame_mjpeg(self.fileName)
		
		# reconnect (this also resets sessionId to 0)
		self.connectToServer()

		self.rtspRunning = True

		# reset state
		self.state = self.INIT
		self.setupEvent.clear()  # Reset setup event for new connection
		
		# setup again - this will send the current frameNbr to server
		self.setupMovie()
		
		# Wait for SETUP to complete before sending PLAY
		if self.setupEvent.wait(timeout=5):  # 5 second timeout
			self.playMovie()
		else:
			print("ERROR: SETUP timeout - quality switch failed")