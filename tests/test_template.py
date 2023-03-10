# -*- coding: utf-8 -*-
#
# Project Kimchi
#
# Copyright IBM Corp, 2015-2017
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301 USA
import json
import os
import unittest
import urllib
from functools import partial

import cherrypy
import iso_gen
import psutil
from wok.plugins.kimchi.config import READONLY_POOL_TYPE
from wok.plugins.kimchi.model.featuretests import FeatureTests
from wok.plugins.kimchi.model.templates import MAX_MEM_LIM

from tests.utils import patch_auth
from tests.utils import request
from tests.utils import run_server

model = None
test_server = None
MOCK_ISO = '/tmp/mock.iso'
DEFAULT_POOL = '/plugins/kimchi/storagepools/default-pool'


def setUpModule():
    global test_server, model

    patch_auth()
    test_server = run_server(test_mode=True)
    model = cherrypy.tree.apps['/plugins/kimchi'].root.model
    iso_gen.construct_fake_iso(MOCK_ISO, True, '14.04', 'ubuntu')


def tearDownModule():
    test_server.stop()


class TemplateTests(unittest.TestCase):
    def setUp(self):
        self.request = partial(request)
        model.reset()

    def test_tmpl_lifecycle(self):
        resp = self.request('/plugins/kimchi/templates')
        self.assertEqual(200, resp.status)
        self.assertEqual(0, len(json.loads(resp.read())))

        # Create a template without cdrom and disk specified fails with 400
        t = {
            'name': 'test',
            'os_distro': 'ImagineOS',
            'os_version': '1.0',
            'memory': {'current': 1024},
            'cpu_info': {'vcpus': 1},
        }
        req = json.dumps(t)
        resp = self.request('/plugins/kimchi/templates', req, 'POST')
        self.assertEqual(400, resp.status)

        # Create a netboot template
        t = {'name': 'test-netboot', 'source_media': {'type': 'netboot'}}
        req = json.dumps(t)
        resp = self.request('/plugins/kimchi/templates', req, 'POST')
        self.assertEqual(201, resp.status)

        # Verify the netboot template
        tmpl = json.loads(self.request(
            '/plugins/kimchi/templates/test-netboot').read())
        self.assertIsNone(tmpl['cdrom'])

        # Delete the netboot template
        resp = self.request(
            '/plugins/kimchi/templates/test-netboot', '{}', 'DELETE')
        self.assertEqual(204, resp.status)

        # Create a template
        t = {'name': 'test', 'source_media': {
            'type': 'disk', 'path': MOCK_ISO}}
        req = json.dumps(t)
        resp = self.request('/plugins/kimchi/templates', req, 'POST')
        self.assertEqual(201, resp.status)

        # Verify the template
        keys = [
            'name',
            'icon',
            'invalid',
            'os_distro',
            'os_version',
            'memory',
            'cdrom',
            'disks',
            'networks',
            'folder',
            'graphics',
            'cpu_info',
        ]
        tmpl = json.loads(self.request(
            '/plugins/kimchi/templates/test').read())
        if os.uname()[4] == 's390x':
            keys.append('interfaces')
        self.assertEqual(sorted(tmpl.keys()), sorted(keys))
        self.assertEqual(t['source_media']['path'], tmpl['cdrom'])
        disk_keys = ['index', 'pool', 'size', 'format']
        disk_pool_keys = ['name', 'type']
        self.assertEqual(sorted(tmpl['disks'][0].keys()), sorted(disk_keys))
        self.assertEqual(
            sorted(tmpl['disks'][0]['pool'].keys()), sorted(disk_pool_keys)
        )

        # Clone a template
        resp = self.request(
            '/plugins/kimchi/templates/test/clone', '{}', 'POST')
        self.assertEqual(303, resp.status)

        # Verify the cloned template
        tmpl_cloned = json.loads(
            self.request('/plugins/kimchi/templates/test-clone1').read()
        )
        del tmpl['name']
        del tmpl_cloned['name']
        self.assertEqual(tmpl, tmpl_cloned)

        # Delete the cloned template
        resp = self.request(
            '/plugins/kimchi/templates/test-clone1', '{}', 'DELETE')
        self.assertEqual(204, resp.status)

        # Create a template with same name fails with 400
        req = json.dumps(
            {'name': 'test', 'source_media': {'type': 'disk', 'path': MOCK_ISO}}
        )
        resp = self.request('/plugins/kimchi/templates', req, 'POST')
        self.assertEqual(400, resp.status)

        # Create an image based template
        os.system('qemu-img create -f qcow2 %s 10G' % '/tmp/mock.img')
        t = {
            'name': 'test_img_template',
            'source_media': {'type': 'disk', 'path': '/tmp/mock.img'},
        }
        req = json.dumps(t)
        resp = self.request('/plugins/kimchi/templates', req, 'POST')
        self.assertEqual(201, resp.status)
        os.remove('/tmp/mock.img')

        # Test disk format
        t = {
            'name': 'test-format',
            'source_media': {'type': 'disk', 'path': MOCK_ISO},
            'disks': [{'size': 10, 'format': 'vmdk', 'pool': {'name': DEFAULT_POOL}}],
        }

        req = json.dumps(t)
        resp = self.request('/plugins/kimchi/templates', req, 'POST')
        self.assertEqual(201, resp.status)
        tmpl = json.loads(self.request(
            '/plugins/kimchi/templates/test-format').read())
        self.assertEqual(tmpl['disks'][0]['format'], 'vmdk')

        # Create template with memory higher than host max
        if hasattr(psutil, 'virtual_memory'):
            max_mem = psutil.virtual_memory().total >> 10 >> 10
        else:
            max_mem = psutil.TOTAL_PHYMEM >> 10 >> 10
        memory = max_mem + 1024
        t = {
            'name': 'test-maxmem',
            'source_media': {'type': 'disk', 'path': MOCK_ISO},
            'memory': {'current': memory},
        }
        req = json.dumps(t)
        resp = self.request('/plugins/kimchi/templates', req, 'POST')
        self.assertEqual(400, resp.status)
        self.assertTrue(str(max_mem) in resp.read().decode('utf-8'))

    def test_customized_tmpl(self):
        # Create a template
        t = {'name': 'test', 'source_media': {
            'type': 'disk', 'path': MOCK_ISO}}
        req = json.dumps(t)
        resp = self.request('/plugins/kimchi/templates', req, 'POST')
        self.assertEqual(201, resp.status)
        tmpl = json.loads(self.request(
            '/plugins/kimchi/templates/test').read())

        # Create another template to test update template name with one of
        # existing template name
        req = json.dumps(
            {'name': 'test_new', 'source_media': {
                'type': 'disk', 'path': MOCK_ISO}}
        )
        resp = self.request('/plugins/kimchi/templates', req, 'POST')
        self.assertEqual(201, resp.status)
        # Update name with one of existing name should fail with 400
        req = json.dumps({'name': 'test_new'})
        resp = self.request('/plugins/kimchi/templates/test', req, 'PUT')
        self.assertEqual(400, resp.status)

        # Delete the test1 template
        resp = self.request(
            '/plugins/kimchi/templates/test_new', '{}', 'DELETE')
        self.assertEqual(204, resp.status)

        # Update name
        new_name = 'k??????h??Tmpl'
        new_tmpl_uri = urllib.parse.quote(
            f'/plugins/kimchi/templates/{new_name}')
        req = json.dumps({'name': new_name})
        resp = self.request('/plugins/kimchi/templates/test', req, 'PUT')
        self.assertEqual(303, resp.status)
        resp = self.request(new_tmpl_uri)
        update_tmpl = json.loads(resp.read())
        self.assertEqual(new_name, update_tmpl['name'])
        del tmpl['name']
        del update_tmpl['name']
        self.assertEqual(tmpl, update_tmpl)

        # Update icon
        req = json.dumps({'icon': 'plugins/kimchi/images/icon-fedora.png'})
        resp = self.request(new_tmpl_uri, req, 'PUT')
        self.assertEqual(200, resp.status)
        update_tmpl = json.loads(resp.read())
        self.assertEqual(
            'plugins/kimchi/images/icon-fedora.png', update_tmpl['icon'])

        # Update os_distro and os_version
        req = json.dumps({'os_distro': 'fedora', 'os_version': '21'})
        resp = self.request(new_tmpl_uri, req, 'PUT')
        self.assertEqual(200, resp.status)
        update_tmpl = json.loads(resp.read())
        self.assertEqual('fedora', update_tmpl['os_distro'])
        self.assertEqual('21', update_tmpl['os_version'])

        # Update maxvcpus only
        req = json.dumps({'cpu_info': {'maxvcpus': 2}})
        resp = self.request(new_tmpl_uri, req, 'PUT')
        self.assertEqual(200, resp.status)
        update_tmpl = json.loads(resp.read())
        self.assertEqual(2, update_tmpl['cpu_info']['maxvcpus'])

        # Update vcpus only
        req = json.dumps({'cpu_info': {'vcpus': 2}})
        resp = self.request(new_tmpl_uri, req, 'PUT')
        self.assertEqual(200, resp.status)
        update_tmpl = json.loads(resp.read())
        self.assertEqual(2, update_tmpl['cpu_info']['vcpus'])

        # Update cpu_info
        cpu_info_data = {
            'cpu_info': {
                'maxvcpus': 2,
                'vcpus': 2,
                'topology': {'sockets': 1, 'cores': 2, 'threads': 1},
            }
        }
        resp = self.request(new_tmpl_uri, json.dumps(cpu_info_data), 'PUT')
        self.assertEqual(200, resp.status)
        update_tmpl = json.loads(resp.read())
        self.assertEqual(update_tmpl['cpu_info'], cpu_info_data['cpu_info'])

        # Test memory and max memory
        # - memory greated than max memory
        req = json.dumps({'memory': {'current': 4096}})
        resp = self.request(new_tmpl_uri, req, 'PUT')
        self.assertEqual(400, resp.status)
        # - max memory greater than limit: 16TiB to PPC and 4TiB to x86
        req = json.dumps({'memory': {'maxmemory': MAX_MEM_LIM + 1024}})
        resp = self.request(new_tmpl_uri, req, 'PUT')
        self.assertEqual(400, resp.status)
        self.assertTrue('KCHVM0079E' in resp.read().decode('utf-8'))
        # - change only max memory
        req = json.dumps({'memory': {'maxmemory': 3072}})
        resp = self.request(new_tmpl_uri, req, 'PUT')
        self.assertEqual(200, resp.status)
        update_tmpl = json.loads(resp.read())
        self.assertEqual(3072, update_tmpl['memory']['maxmemory'])
        # - change only memory
        req = json.dumps({'memory': {'current': 2048}})
        resp = self.request(new_tmpl_uri, req, 'PUT')
        self.assertEqual(200, resp.status)
        update_tmpl = json.loads(resp.read())
        self.assertEqual(2048, update_tmpl['memory']['current'])
        self.assertEqual(3072, update_tmpl['memory']['maxmemory'])
        # - change both values
        req = json.dumps({'memory': {'current': 1024, 'maxmemory': 1024}})
        resp = self.request(new_tmpl_uri, req, 'PUT')
        self.assertEqual(200, resp.status)
        update_tmpl = json.loads(resp.read())
        self.assertEqual(1024, update_tmpl['memory']['current'])
        self.assertEqual(1024, update_tmpl['memory']['maxmemory'])

        # Update cdrom
        cdrom_data = {'cdrom': 'inexistent.iso'}
        resp = self.request(new_tmpl_uri, json.dumps(cdrom_data), 'PUT')
        self.assertEqual(400, resp.status)

        cdrom_data = {'cdrom': '/tmp/existent.iso'}
        resp = self.request(new_tmpl_uri, json.dumps(cdrom_data), 'PUT')
        self.assertEqual(200, resp.status)
        update_tmpl = json.loads(resp.read())
        self.assertEqual(update_tmpl['cdrom'], cdrom_data['cdrom'])

        # Update disks
        disk_data = {
            'disks': [
                {
                    'index': 0,
                    'size': 10,
                    'format': 'raw',
                    'pool': {'name': DEFAULT_POOL},
                },
                {
                    'index': 1,
                    'size': 20,
                    'format': 'qcow2',
                    'pool': {'name': DEFAULT_POOL},
                },
            ]
        }
        resp = self.request(new_tmpl_uri, json.dumps(disk_data), 'PUT')
        self.assertEqual(200, resp.status)
        resp = self.request(new_tmpl_uri)
        self.assertEqual(200, resp.status)
        updated_tmpl = json.loads(resp.read())
        disk_data['disks'][0]['pool'] = {'name': DEFAULT_POOL, 'type': 'dir'}

        disk_data['disks'][1]['pool'] = {'name': DEFAULT_POOL, 'type': 'dir'}
        self.assertEqual(updated_tmpl['disks'], disk_data['disks'])

        # For all supported types, edit the template and check if
        # the change was made.
        disk_types = ['qcow', 'qcow2', 'qed', 'raw', 'vmdk', 'vpc']
        for disk_type in disk_types:
            disk_data = {
                'disks': [
                    {
                        'index': 0,
                        'format': disk_type,
                        'size': 10,
                        'pool': {'name': DEFAULT_POOL},
                    }
                ]
            }
            resp = self.request(new_tmpl_uri, json.dumps(disk_data), 'PUT')
            self.assertEqual(200, resp.status)

            resp = self.request(new_tmpl_uri)
            self.assertEqual(200, resp.status)
            updated_tmpl = json.loads(resp.read())
            disk_data['disks'][0]['pool'] = {
                'name': DEFAULT_POOL, 'type': 'dir'}
            self.assertEqual(updated_tmpl['disks'], disk_data['disks'])

        # Update folder
        folder_data = {'folder': ['mock', 'isos']}
        resp = self.request(new_tmpl_uri, json.dumps(folder_data), 'PUT')
        self.assertEqual(200, resp.status)
        update_tmpl = json.loads(resp.read())
        self.assertEqual(update_tmpl['folder'], folder_data['folder'])

        # Test graphics merge
        req = json.dumps({'graphics': {'type': 'spice'}})
        resp = self.request(new_tmpl_uri, req, 'PUT')
        self.assertEqual(200, resp.status)
        update_tmpl = json.loads(resp.read())
        self.assertEqual('spice', update_tmpl['graphics']['type'])

        # update only listen (type does not reset to default 'vnc')
        req = json.dumps({'graphics': {'listen': 'fe00::0'}})
        resp = self.request(new_tmpl_uri, req, 'PUT')
        self.assertEqual(200, resp.status)
        update_tmpl = json.loads(resp.read())
        self.assertEqual('spice', update_tmpl['graphics']['type'])
        self.assertEqual('fe00::0', update_tmpl['graphics']['listen'])

        # update only type (listen does not reset to default '127.0.0.1')
        req = json.dumps({'graphics': {'type': 'vnc'}})
        resp = self.request(new_tmpl_uri, req, 'PUT')
        self.assertEqual(200, resp.status)
        update_tmpl = json.loads(resp.read())
        self.assertEqual('vnc', update_tmpl['graphics']['type'])
        self.assertEqual('fe00::0', update_tmpl['graphics']['listen'])

    def test_customized_network(self):
        # Create a template
        t = {'name': 'test', 'source_media': {
            'type': 'disk', 'path': MOCK_ISO}}
        req = json.dumps(t)
        resp = self.request('/plugins/kimchi/templates', req, 'POST')
        self.assertEqual(201, resp.status)

        # Create networks to be used for testing
        networks = [
            {'name': 'k??????h??-??et', 'connection': 'isolated'},
            {'name': 'nat-network', 'connection': 'nat'},
            {'name': 'subnet-network', 'connection': 'nat',
                'subnet': '127.0.100.0/24'},
        ]

        # Verify the current system has at least one interface to create a
        # bridged network
        interfaces = json.loads(
            self.request(
                '/plugins/kimchi/interfaces?_inuse=false&type=nic').read()
        )
        if len(interfaces) > 0:
            iface = interfaces[0]['name']
            networks.append(
                {
                    'name': 'bridge-network',
                    'connection': 'macvtap',
                    'interfaces': [iface],
                }
            )
            if not FeatureTests.is_nm_running():
                networks.append(
                    {
                        'name': 'bridge-network-with-vlan',
                        'connection': 'bridge',
                        'interfaces': [iface],
                        'vlan_id': 987,
                    }
                )

        tmpl_nets = []
        for net in networks:
            self.request('/plugins/kimchi/networks', json.dumps(net), 'POST')
            tmpl_nets.append(net['name'])
            req = json.dumps({'networks': tmpl_nets})
            resp = self.request('/plugins/kimchi/templates/test', req, 'PUT')
            self.assertEqual(200, resp.status)

    def test_customized_storagepool(self):
        # Create a template
        t = {'name': 'test', 'source_media': {
            'type': 'disk', 'path': MOCK_ISO}}
        req = json.dumps(t)
        resp = self.request('/plugins/kimchi/templates', req, 'POST')
        self.assertEqual(201, resp.status)

        # MockModel always returns 2 partitions (vdx, vdz)
        partitions = json.loads(self.request(
            '/plugins/kimchi/host/partitions').read())
        devs = [dev['path'] for dev in partitions]

        # MockModel always returns 3 FC devices
        fc_devs = json.loads(
            self.request('/plugins/kimchi/host/devices?_cap=fc_host').read()
        )
        fc_devs = [dev['name'] for dev in fc_devs]

        poolDefs = [
            {
                'type': 'dir',
                'name': 'k??????h??UnitTestDirPool',
                'path': '/tmp/kimchi-images',
            },
            {
                'type': 'netfs',
                'name': 'k??????h??UnitTestNSFPool',
                'source': {'host': 'localhost', 'path': '/var/lib/kimchi/nfs-pool'},
            },
            {
                'type': 'scsi',
                'name': 'k??????h??UnitTestSCSIFCPool',
                'source': {'adapter_name': fc_devs[0]},
            },
            {
                'type': 'iscsi',
                'name': 'k??????h??UnitTestISCSIPool',
                'source': {
                    'host': '127.0.0.1',
                    'target': 'iqn.2015-01.localhost.kimchiUnitTest',
                },
            },
            {
                'type': 'logical',
                'name': 'k??????h??UnitTestLogicalPool',
                'source': {'devices': [devs[0]]},
            },
        ]

        for pool in poolDefs:
            resp = self.request(
                '/plugins/kimchi/storagepools', json.dumps(pool), 'POST'
            )
            self.assertEqual(201, resp.status)
            pool_uri = urllib.parse.quote(
                f"/plugins/kimchi/storagepools/{pool['name']}"
            )
            resp = self.request(pool_uri + '/activate', '{}', 'POST')
            self.assertEqual(200, resp.status)

            req = None
            unquoted_pool_uri = urllib.parse.unquote(pool_uri)
            if pool['type'] in READONLY_POOL_TYPE:
                resp = self.request(pool_uri + '/storagevolumes')
                vols = json.loads(resp.read())
                if len(vols) > 0:

                    vol = vols[0]['name']
                    req = json.dumps(
                        {
                            'disks': [
                                {
                                    'volume': vol,
                                    'pool': {'name': unquoted_pool_uri},
                                    'format': 'raw',
                                }
                            ]
                        }
                    )
            elif pool['type'] == 'logical':
                req = json.dumps(
                    {
                        'disks': [
                            {
                                'pool': {'name': unquoted_pool_uri},
                                'format': 'raw',
                                'size': 10,
                            }
                        ]
                    }
                )
            else:
                req = json.dumps(
                    {
                        'disks': [
                            {
                                'pool': {'name': unquoted_pool_uri},
                                'format': 'qcow2',
                                'size': 10,
                            }
                        ]
                    }
                )

            if req is not None:
                resp = self.request(
                    '/plugins/kimchi/templates/test', req, 'PUT')
                self.assertEqual(200, resp.status)

        # Test disk template update with different pool
        pool_uri = '/plugins/kimchi/storagepools/k??????h??UnitTestDirPool'
        disk_data = {
            'disks': [{'size': 5, 'format': 'qcow2', 'pool': {'name': pool_uri}}]
        }
        req = json.dumps(disk_data)
        resp = self.request('/plugins/kimchi/templates/test', req, 'PUT')
        self.assertEqual(200, resp.status)
        del disk_data['disks'][0]['pool']
        disk_data['disks'][0]['index'] = 0
        disk_data['disks'][0]['pool'] = {'name': pool_uri, 'type': 'dir'}
        tmpl = json.loads(self.request(
            '/plugins/kimchi/templates/test').read())
        self.assertListEqual(
            sorted(disk_data['disks'][0].keys()), sorted(
                tmpl['disks'][0].keys())
        )
        self.assertListEqual(
            list(disk_data['disks'][0].values()), list(
                tmpl['disks'][0].values())
        )

    def test_tmpl_integrity(self):
        mock_iso2 = '/tmp/mock2.iso'
        iso_gen.construct_fake_iso(mock_iso2, True, '14.04', 'ubuntu')
        # Create a network and a pool for testing template integrity
        net = {'name': 'nat-network', 'connection': 'nat'}
        resp = self.request('/plugins/kimchi/networks',
                            json.dumps(net), 'POST')
        self.assertEqual(201, resp.status)

        pool = {'type': 'dir', 'name': 'dir-pool', 'path': '/tmp/dir-pool'}
        resp = self.request('/plugins/kimchi/storagepools',
                            json.dumps(pool), 'POST')
        self.assertEqual(201, resp.status)
        pool_uri = f"/plugins/kimchi/storagepools/{pool['name']}"
        resp = self.request(pool_uri + '/activate', '{}', 'POST')
        self.assertEqual(200, resp.status)

        # Create a template using the custom network and pool
        t = {
            'name': 'test',
            'source_media': {'type': 'disk', 'path': mock_iso2},
            'networks': ['nat-network'],
            'disks': [
                {
                    'pool': {'name': '/plugins/kimchi/storagepools/dir-pool'},
                    'size': 2,
                    'format': 'qcow2',
                }
            ],
        }
        req = json.dumps(t)
        resp = self.request('/plugins/kimchi/templates', req, 'POST')
        self.assertEqual(201, resp.status)

        # Try to delete network
        # It should fail as it is associated to a template
        resp = self.request(
            '/plugins/kimchi/networks/nat-network', '{}', 'DELETE')
        self.assertIn('KCHNET0017E', json.loads(resp.read())['reason'])

        # Update template to release network and then delete it
        params = {'networks': []}
        req = json.dumps(params)
        self.request('/plugins/kimchi/templates/test', req, 'PUT')
        resp = self.request(
            '/plugins/kimchi/networks/nat-network', '{}', 'DELETE')
        self.assertEqual(204, resp.status)

        # Try to delete the storagepool
        # It should fail as it is associated to a template
        resp = self.request(
            '/plugins/kimchi/storagepools/dir-pool', '{}', 'DELETE')
        self.assertEqual(400, resp.status)

        # Verify the template
        os.remove(mock_iso2)
        res = json.loads(self.request('/plugins/kimchi/templates/test').read())
        self.assertEqual(res['invalid']['cdrom'], [mock_iso2])
