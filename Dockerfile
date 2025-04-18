FROM python:3.9-slim

WORKDIR /app

# Copy the DHCP server script
COPY dhcp_server.py .
COPY requirements.txt .

# Install dependencies (if any)
RUN pip install -r requirements.txt

# Expose DHCP ports
EXPOSE 67/udp
EXPOSE 68/udp

# Run the DHCP server
CMD ["python", "dhcp_server.py"] 