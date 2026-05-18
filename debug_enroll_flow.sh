#!/usr/bin/env bash
set -euo pipefail
COOKIEJAR=/tmp/campus_debug_cookies2.txt
rm -f "$COOKIEJAR"

echo "Signing up..."
curl -s -c "$COOKIEJAR" -X POST -d "full_name=Script User&student_id=5005&email=script@ex.com&password=pass" http://127.0.0.1:5000/signup -o /tmp/signup_script.html

echo "Logging in..."
curl -s -b "$COOKIEJAR" -c "$COOKIEJAR" -L -X POST -d "email=script@ex.com&password=pass" http://127.0.0.1:5000/login -o /tmp/login_script.html

echo "Enroll CS101:"
curl -s -b "$COOKIEJAR" -H "Content-Type: application/json" -X POST -d '{"course_id":"CS101"}' http://127.0.0.1:5000/enroll | jq . || cat -

echo "Complete CS101:"
curl -s -b "$COOKIEJAR" -H "Content-Type: application/json" -X POST -d '{"course_id":"CS101"}' http://127.0.0.1:5000/complete | jq . || cat -

echo "Enroll CS201:"
curl -s -b "$COOKIEJAR" -H "Content-Type: application/json" -X POST -d '{"course_id":"CS201"}' http://127.0.0.1:5000/enroll | jq . || cat -

echo "Enroll CS202:"
curl -s -b "$COOKIEJAR" -H "Content-Type: application/json" -X POST -d '{"course_id":"CS202"}' http://127.0.0.1:5000/enroll | jq . || cat -

echo "Status:"
curl -s -b "$COOKIEJAR" http://127.0.0.1:5000/status | jq . || cat -

echo "Done."
