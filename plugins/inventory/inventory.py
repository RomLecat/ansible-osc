from ansible.errors import AnsibleError
from ansible.module_utils.basic import missing_required_lib
from ansible.plugins.inventory import BaseInventoryPlugin, Constructable
import os

HAS_OSC_SDK = True
try:
    from osc_sdk_python import Gateway
except ImportError:
    HAS_OSC_SDK = False

DOCUMENTATION = r'''
name: inventory
plugin_type: inventory
short_description: Outscale VM inventory source
author: "Romain Lecat"
description:
  - Get inventory hosts from the Outscale cloud platform.
  - Uses an YAML configuration file ending with 'outscale.yml' or 'outscale.yaml' to set parameter values.
  - Uses Outscale SDK (osc-sdk-python) - must be installed separately.
options:
  access_key:
    description: Outscale access key.
    type: string
    env:
      - name: OSC_ACCESS_KEY
  secret_key:
    description: Outscale secret key.
    type: string
    env:
      - name: OSC_SECRET_KEY
  region:
    description: Outscale region.
    type: string
    default: eu-west-2
    env:
      - name: OSC_REGION
  filters:
    description: A dictionary of filters to apply to the ReadVms API call.
    type: dict
    default: {}
  hostname_variable:
    description: Which VM attribute to use as the Ansible hostname.
    type: string
    choices: [vm_id, public_ip, private_ip, tag_Name]
    default: tag_Name
  ip_preference:
    description: Which IP to use for ansible_host.
    type: string
    choices: [prefer_public, public_only, private_only]
    default: prefer_public
  group_by:
    description: Keys to create Ansible groups from.
    type: list
    default: [tags, region, subregion, vm_type, state]
    choices: [tags, region, subregion, vm_type, state]
  compose:
    description: Create vars from jinja2 expressions.
    type: dict
    default: {}
  groups:
    description: Add hosts to group based on Jinja2 conditionals.
    type: dict
    default: {}
  keyed_groups:
    description: Add hosts to group based on the values of a variable.
    type: list
    default: []
  leading_separator:
    description: Use in conjunction with keyed_groups.
    type: bool
    default: true
  strict:
    description: If 'yes' make invalid entries a fatal error, otherwise skip and continue.
    type: bool
    default: false
requirements:
  - osc-sdk-python
'''

class InventoryModule(BaseInventoryPlugin, Constructable):

    NAME = 'inventory'

    def verify_file(self, path):
        """Return true/false if this is a valid file for this plugin to consume"""
        valid = False
        if super(InventoryModule, self).verify_file(path):
            if path.endswith(('outscale.yaml', 'outscale.yml')):
                valid = True
        return valid

    def parse(self, inventory, loader, path, cache=True):
        super(InventoryModule, self).parse(inventory, loader, path)
        config = self._read_config_data(path)  # Parse the YAML config file into a dict

        if not HAS_OSC_SDK:
            raise AnsibleError(missing_required_lib('osc-sdk-python'))

        # Get options directly from config dict (with defaults) or env
        access_key = config.get('access_key') or os.getenv('OSC_ACCESS_KEY')
        secret_key = config.get('secret_key') or os.getenv('OSC_SECRET_KEY')
        region = config.get('region', 'eu-west-2') or os.getenv('OSC_REGION')
        filters = config.get('filters', {})
        hostname_variable = config.get('hostname_variable', 'tag_Name')
        ip_preference = config.get('ip_preference', 'public_or_private')
        group_by = config.get('group_by', ['tags', 'region', 'subregion', 'vm_type', 'state'])

        # Get Constructable options from config
        compose = config.get('compose', {})
        groups = config.get('groups', {})
        keyed_groups = config.get('keyed_groups', [])
        strict = config.get('strict', False)

        # Error handling for missing credentials
        if not access_key or not secret_key:
            raise AnsibleError("Outscale access_key and secret_key must be provided via the configuration file or environment variables (OSC_ACCESS_KEY, OSC_SECRET_KEY).")

        # Initialize Gateway
        gw_params = {}
        if access_key:
            gw_params['access_key'] = access_key
        if secret_key:
            gw_params['secret_key'] = secret_key
        if region:
            gw_params['region'] = region
        gw = Gateway(**gw_params)

        # Fetch all VMs with pagination
        vms = []
        params = {'Filters': filters}
        next_token = None
        while True:
            if next_token:
                params['NextPageToken'] = next_token
            response = gw.ReadVms(**params)
            vms.extend(response.get('Vms', []))
            next_token = response.get('NextPageToken')
            if not next_token:
                break

        # Process each VM
        for vm in vms:
            # Determine hostname
            if hostname_variable == 'vm_id':
                hostname = vm.get('VmId')
            elif hostname_variable == 'public_ip':
                hostname = vm.get('PublicIp')
            elif hostname_variable == 'private_ip':
                hostname = vm.get('PrivateIp')
            elif hostname_variable == 'tag_Name':
                tags = {tag['Key']: tag['Value'] for tag in vm.get('Tags', []) if 'Value' in tag}
                hostname = tags.get('Name', vm.get('VmId'))
            if not hostname:
                continue

            # Add host
            inventory.add_host(hostname)

            # Set ansible_host based on ip_preference
            public_ip = vm.get('PublicIp')
            private_ip = vm.get('PrivateIp')
            if ip_preference == 'public_only':
                ansible_host = public_ip if public_ip else None
            elif ip_preference == 'private_only':
                ansible_host = private_ip if private_ip else None
            elif ip_preference == 'prefer_public':
                ansible_host = public_ip if public_ip else private_ip
            else:
                raise AnsibleError(f"Invalid parameter value for ip_preference: {ip_preference}")

            if ansible_host:
                inventory.set_variable(hostname, 'ansible_host', ansible_host)

            # Set other variables
            inventory.set_variable(hostname, 'outscale_vm_id', vm.get('VmId'))
            inventory.set_variable(hostname, 'outscale_state', vm.get('State'))
            inventory.set_variable(hostname, 'outscale_vm_type', vm.get('VmType'))
            inventory.set_variable(hostname, 'outscale_subregion', vm.get('Placement', {}).get('SubregionName'))
            inventory.set_variable(hostname, 'outscale_tags', {tag['Key']: tag['Value'] for tag in vm.get('Tags', []) if 'Value' in tag})

            # Build host_vars dict from set variables (for Constructable)
            host_vars = {}
            for var in ['ansible_host', 'outscale_vm_id', 'outscale_state', 'outscale_vm_type', 'outscale_subregion', 'outscale_tags']:
                value = inventory.get_host(hostname).get_vars().get(var)
                if value is not None:
                    host_vars[var] = value

            # Apply Constructable features
            self._set_composite_vars(compose, host_vars, hostname, strict=strict)
            self._add_host_to_composed_groups(groups, host_vars, hostname, strict=strict)
            self._add_host_to_keyed_groups(keyed_groups, host_vars, hostname, strict=strict)

            # Add to groups (existing logic)
            if 'tags' in group_by:
                for key, value in {tag['Key']: tag['Value'] for tag in vm.get('Tags', []) if 'Value' in tag}.items():
                    safe_value = str(value or '').replace(":", "_").replace("/", "_").replace(" ", "_")
                    group_name = f'tag_{key}_{safe_value}'
                    inventory.add_group(group_name)
                    inventory.add_child(group_name, hostname)

            if 'region' in group_by and region:
                inventory.add_group(region)
                inventory.add_child(region, hostname)

            if 'subregion' in group_by:
                subregion = vm.get('Placement', {}).get('SubregionName')
                if subregion:
                    inventory.add_group(subregion)
                    inventory.add_child(subregion, hostname)

            if 'vm_type' in group_by:
                vm_type = vm.get('VmType')
                if vm_type:
                    inventory.add_group(f'vm_type_{vm_type}')
                    inventory.add_child(f'vm_type_{vm_type}', hostname)

            if 'state' in group_by:
                state = vm.get('State')
                if state:
                    inventory.add_group(f'state_{state}')
                    inventory.add_child(f'state_{state}', hostname)
