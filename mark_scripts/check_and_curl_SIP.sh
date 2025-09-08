#!/bin/bash

# This script corrects a strange problem that occurs with SIP service not initializing properly if experiencing power failure during a running cysle.
#
# Function to wait for server 
wait_for_server() {
  echo "Waiting for http://localhost:80 to respond from SIP server ..."
  until curl -s --head http://localhost:80 | grep "200 OK"; do
    echo "sleep 5"
    sleep 5
  done
  echo "Response 200 OK received, server is up!"
}

# Function to send curl and report status
send_request() {
  local url=$1
  echo "Sending request to $url"
  response=$(curl -s -w "HTTP_CODE:%{http_code}" "$url")
  body=$(echo "$response" | sed 's/HTTP_CODE:.*//')
  code=$(echo "$response" | grep -o 'HTTP_CODE:[0-9]*' | cut -d: -f2)

  echo "HTTP Status: $code"
  echo "Response Body:"
  echo "$body"
}

# Wait for server
wait_for_server

echo "Now delaying 60 seconds before sending curl commands to toggle manual"
echo "mode on and off (fixes bug if power lost under a program cycle."
sleep 60

# Send requests
send_request "http://localhost:80/cv?mm=1"
sleep 1
send_request "http://localhost:80/cv?mm=0"
send_request "http://localhost:80/cv?rst=1"

