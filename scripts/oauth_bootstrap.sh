#!/usr/bin/env bash
# Run the existing helper to create token interactively (not stored in repo)
python3 ../nixos-helix/tools/gmail_oauth_setup.py --credentials "$HOME/.config/gwen/gmail_credentials.json" --token "$HOME/.config/gwen/gmail_token.json"
