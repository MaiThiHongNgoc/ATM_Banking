import os

# Tạo một khóa bí mật ngẫu nhiên
secret_key = os.urandom(24)  # 24 byte (192-bit key)
print(secret_key)
