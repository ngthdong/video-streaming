class Utils:
    @staticmethod
    def get_total_frame_mjpeg(file_path):
        total_frames = 0

        with open(file_path, 'rb') as f:
            while True:
                # Read frame length (5 bytes)
                length_bytes = f.read(5)
                if not length_bytes:
                    break

                try:
                    frame_length = int(length_bytes)
                except ValueError:
                    break

                # Skip frame data
                f.read(frame_length)
                total_frames += 1

        return total_frames
    
    @staticmethod
    def format_time_mmss(time: int):
        return time // 60, time % 60