#!/usr/bin/env python

import json

import boto3
from botocore.config import Config

regions = [
    'ap-south-1',
]

boto3_session = boto3.session.Session(profile_name='sso')

I = {
    '_meta': {
        'hostvars': {}
    },
    'all': {
        'hosts': [

        ],
        'children': [
            'ungrouped',
            'metrics',
            'eth2stats_server',
            'bootnode',
            'eth2client',
            'beacon_node',
        ]
    },
    'metrics': {
        'hosts': [],
        'vars': {}
    },
    'eth2stats_server': {
        'hosts': []
    },
    'bootnode': {
        'hosts': []
    },
    'beacon_node': {
        'hosts': [],
    },
    'eth2client': {
        'hosts': [],
        'children': [
            'eth2client_lighthouse',
            'eth2client_nimbus',
            'eth2client_prysm',
            'eth2client_teku'
        ]
    },
    'eth2client_lighthouse': {
        'hosts': [],
    },
    'eth2client_nimbus': {
        'hosts': [],
    },
    'eth2client_prysm': {
        'hosts': [],
    },
    'eth2client_teku': {
        'hosts': [],
    },
    'ungrouped': {
        'children': [
        ]
    }
}

eth2_clients = [
    'lighthouse',
    'nimbus',
    'prysm',
    'teku'
]

for reg in regions:
    for cl in eth2_clients:
        I[f'eth2client_{cl}_{reg.replace("-", "_")}'] = {'hosts': []}
    I[f'eth2client_all_{reg.replace("-", "_")}'] = {'hosts': []}

filters = [
    {'Name': 'tag:Environment', 'Values': ['mergenet0']},
    {'Name': 'tag:Project', 'Values': ['inventory']},
    {'Name': 'tag:Team', 'Values': ['eth2']},
    {'Name': 'instance-state-name', 'Values': ['running']},
]


def get_instances():
    for r in regions:
        ec2 = boto3_session.resource('ec2', region_name=r)
        instances = ec2.instances.filter(Filters=filters)
        for i in instances:
            yield i


for i in get_instances():
    name = i.id
    role = 'unknown'
    for tag in i.tags:
        if tag['Key'] == 'Name':
            name = tag['Value']
        if tag['Key'] == 'Role':
            role = tag['Value']

    I['beacon_node']['hosts'].append(name)

    I['all']['hosts'].append(name)
    region = str(i.placement['AvailabilityZone'])
    region = region[:region.rindex('-') + 2]  # strip of the a, b, whatever zone suffix from the region

    parts = name.split('-')
    node_idx = int(parts[-1])

    I['_meta']['hostvars'][name] = {
        'ansible_host': i.public_ip_address,  # ip that we use for ansible work.
        'public_ip_address': i.public_ip_address,  # ip that we use for p2p / configs / etc., generally the same
        'region': region,
        'node_index': node_idx,
    }

# TODO: give all nodes client types etc.

def get_node_public_ips(groupname):
    for n in I[groupname]['hosts']:
        yield n, I['_meta']['hostvars'][n]['public_ip_address']

def get_client_ips(client):
    return get_node_public_ips('eth2client_' + client)

def get_client_metrics_targets(client):
    for node, ip in get_client_ips(client):
        yield f'{ip}:8100'
        yield f'{ip}:8080'

I['metrics']['vars'] = {
    **I['metrics']['vars'],
    'prometheus_settings': {
        'alerting': {
                'alertmanagers': [
                    {
                    'scheme': 'http',
                    'static_configs': [
                        {
                            'targets': [
                                # Alertmanager is accessible via the docker bridge network promnet at this IP address:Port
                                '172.1.1.103:9093'
                            ]
                        }
                    ],
                    }
                ]
        },
        'rule_files': [
            'alert.rules'
        ],
        'scrape_configs': [
            {
                'job_name': 'eth2stats',
                'scrape_interval': '5s',
                'metrics_path': '/metrics',
                'static_configs': [
                    {
                        'targets': [
                            f'{ip}:8100' for ip in get_node_public_ips('eth2stats_server')
                        ]
                    }
                ]
            },
            {
                'job_name': 'bootnode',
                'scrape_interval': '5s',
                'metrics_path': '/metrics',
                'static_configs': [
                    {
                        'targets': [f'{ip}:8100' for ip in get_node_public_ips('bootnode')]
                    }
                ]
            },
            {
                'job_name': 'beacon',
                'scrape_interval': '12s',  # we're scraping lots of data, don't go to fast, just do it once per slot.
                'metrics_path': '/metrics',
                'static_configs': [
                    {
                        'labels': {
                            'eth2client': eth2client
                        },
                        'targets': list(get_client_metrics_targets(eth2client))
                    } for eth2client in eth2_clients
                ]
            }
        ]
    }
}

print(json.dumps(I, indent=4))
