import sys
from time import time
HEADER_SIZE = 12
FRAGMENTATION_HEADER_SIZE = 8  # frame_id(4) + frag_index(1) + total_frags(1) + reserved(2)

class RtpPacket:	
	header = bytearray(HEADER_SIZE)
	fragmentation_header = None
	
	def __init__(self):
		pass
		
	def encode(self, version, padding, extension, cc, seqnum, marker, pt, ssrc, payload, 
		   fragmentation_info=None):
		"""Encode the RTP packet with header fields and payload.
		
		Args:
			fragmentation_info: dict with keys:
				- frame_id: unique frame identifier
				- fragment_index: current fragment index (0-based)
				- total_fragments: total number of fragments for this frame
		"""
		timestamp = int(time())
		header = bytearray(HEADER_SIZE)
		
		# Byte 0: Version, Padding, Extension, CC
		header[0] = (version << 6) | (padding << 5) | (extension << 4) | cc

		# Byte 1: Marker, Payload Type
		header[1] = (marker << 7) | pt

		# Byte 2-3: Sequence Number
		header[2] = (seqnum >> 8) & 255
		header[3] = seqnum & 255

		# Byte 4-7: Timestamp
		header[4] = (timestamp >> 24) & 255
		header[5] = (timestamp >> 16) & 255
		header[6] = (timestamp >> 8) & 255
		header[7] = timestamp & 255

		# Byte 8-11: SSRC
		header[8]  = (ssrc >> 24) & 255
		header[9]  = (ssrc >> 16) & 255
		header[10] = (ssrc >> 8) & 255
		header[11] = ssrc & 255

		# Save header and payload
		self.header = header
		self.payload = payload
		
		# Handle fragmentation header if needed
		if fragmentation_info:
			frag_header = bytearray(FRAGMENTATION_HEADER_SIZE)
			frame_id = fragmentation_info['frame_id']
			frag_index = fragmentation_info['fragment_index']
			total_frags = fragmentation_info['total_fragments']
			
			# Byte 0-3: Frame ID (4 bytes, big-endian)
			frag_header[0] = (frame_id >> 24) & 255
			frag_header[1] = (frame_id >> 16) & 255
			frag_header[2] = (frame_id >> 8) & 255
			frag_header[3] = frame_id & 255
			
			# Byte 4: Fragment Index
			frag_header[4] = frag_index & 255
			
			# Byte 5: Total Fragments
			frag_header[5] = total_frags & 255
			
			# Byte 6: Magic marker (0xFF indicates fragmentation header present)
			frag_header[6] = 0xFF
			# Byte 7: Reserved
			frag_header[7] = 0
			
			self.fragmentation_header = frag_header
		else:
			self.fragmentation_header = None
		
	def decode(self, byteStream):
		"""Decode the RTP packet."""
		self.header = bytearray(byteStream[:HEADER_SIZE])
		
		# Check if there's a fragmentation header by examining payload
		# Fragmentation header is 8 bytes and follows the RTP header
		remaining_data = byteStream[HEADER_SIZE:]
		
		# Try to detect fragmentation header (simple heuristic: check if first 4 bytes look like frame_id)
		# For now, we'll use a marker approach - check if payload starts with specific pattern
		self.fragmentation_header = None
		self.payload = remaining_data
	
	def decode_with_fragmentation(self, byteStream):
		"""Decode RTP packet with fragmentation header.
		
		Fragmentation header is detected by magic marker (0xFF) at byte 6.
		"""
		self.header = bytearray(byteStream[:HEADER_SIZE])
		
		# Check for fragmentation header marker at byte 6 of potential frag header
		if len(byteStream) > HEADER_SIZE + 6 and byteStream[HEADER_SIZE + 6] == 0xFF:
			# Magic marker found - fragmentation header is present
			if len(byteStream) >= HEADER_SIZE + FRAGMENTATION_HEADER_SIZE:
				self.fragmentation_header = bytearray(byteStream[HEADER_SIZE:HEADER_SIZE + FRAGMENTATION_HEADER_SIZE])
				self.payload = byteStream[HEADER_SIZE + FRAGMENTATION_HEADER_SIZE:]
			else:
				# Malformed packet but still try to set it
				self.fragmentation_header = bytearray(byteStream[HEADER_SIZE:])
				self.payload = b''
		else:
			# No magic marker - this is a non-fragmented packet
			self.fragmentation_header = None
			self.payload = byteStream[HEADER_SIZE:]
	
	
	def version(self):
		"""Return RTP version."""
		return int(self.header[0] >> 6)
	
	def seqNum(self):
		"""Return sequence (frame) number."""
		seqNum = self.header[2] << 8 | self.header[3]
		return int(seqNum)
	
	def timestamp(self):
		"""Return timestamp."""
		timestamp = self.header[4] << 24 | self.header[5] << 16 | self.header[6] << 8 | self.header[7]
		return int(timestamp)
	
	def payloadType(self):
		"""Return payload type."""
		pt = self.header[1] & 127
		return int(pt)
	
	def getPayload(self):
		"""Return payload."""
		return self.payload
		
	def getFragmentationInfo(self):
		"""Return fragmentation info from fragmentation header."""
		if not self.fragmentation_header:
			return None
		
		frame_id = (self.fragmentation_header[0] << 24 | 
				   self.fragmentation_header[1] << 16 | 
				   self.fragmentation_header[2] << 8 | 
				   self.fragmentation_header[3])
		fragment_index = self.fragmentation_header[4]
		total_fragments = self.fragmentation_header[5]
		
		return {
			'frame_id': frame_id,
			'fragment_index': fragment_index,
			'total_fragments': total_fragments
		}
		
	def getPacket(self):
		"""Return RTP packet."""
		if self.fragmentation_header:
			return self.header + self.fragmentation_header + self.payload
		else:
			return self.header + self.payload
	