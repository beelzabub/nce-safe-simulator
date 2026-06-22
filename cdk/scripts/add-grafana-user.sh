#!/usr/bin/env bash
aws grafana update-permissions \
  --workspace-id g-acdbcc3e21 \
  --update-instruction-batch '[{"action":"ADD","role":"ADMIN","users":[{"id":"68f15380-f0d1-70fa-314b-b561ab686952","type":"SSO_USER"}]}]'
