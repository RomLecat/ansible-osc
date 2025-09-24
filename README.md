# Ansible Collection - romlecat.osc

This collection provides a dynamic inventory plugin for Outscale FCU VMs.

## Status
> [!WARNING]  
> This project is not production ready by any means and not supported nor maintained by Outscale. It is a simple plugin meant for my personal usage.

Contributions for new features or bugfixes are welcome.

## Requirements
- Ansible (Tested on 2.18, should work on >= 2.9)
- osc-sdk-python (`pip install osc-sdk-python`)

## Installation
```bash
ansible-galaxy collection install romlecat.osc_inventory
```

## Configuration example

```yaml
plugin: outscale
region: eu-west-2
access_key:
secret_key:
use_private_ip: true
keyed_groups:
  - key: ansible_categories
    separator: ''
filters:
  VmStateNames: ["running"]
  NetIds: ["vpc-abcdefgh"]
compose:
  ansible_categories: outscale_tags.Ansible | default('') | split(',') | reject('equalto', '') | list

```
