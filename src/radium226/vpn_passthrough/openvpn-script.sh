#!/usr/bin/env bash


NETNS_NAME="%NETNS_NAME%"
HOOK_TYPE="%HOOK_TYPE%"


main() {
    case "${HOOK_TYPE}" in
        up )
            touch "/tmp/openvpn-${NETNS_NAME}.ready"
            ;;
        down )
            rm "/tmp/openvpn-${NETNS_NAME}.ready"
            ;;
        *)
            echo "Unknown hook type: ${HOOK_TYPE}"
            exit 1
            ;;
    esac
    
}


main "${@}"