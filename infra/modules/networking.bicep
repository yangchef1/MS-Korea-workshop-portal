// =============================================================================
// Networking — VNet, Subnets, Private Endpoint, Private DNS Zone
// =============================================================================
// Creates the virtual network infrastructure required for Container Apps VNet
// integration and Storage Account private endpoint connectivity.
//
// Resources:
//   - VNet (10.0.0.0/16)
//   - snet-container-apps  (/23) — delegated to Microsoft.App/environments
//   - snet-private-endpoints (/27) — for storage private endpoint
//   - Private Endpoint targeting the workshop Storage Account (table sub-resource)
//   - Private DNS Zone: privatelink.table.core.windows.net
//   - VNet link for DNS Zone
//   - DNS Zone Group (auto-registers A record for the private endpoint)

@description('Environment name for naming.')
@allowed(['dev', 'prod'])
param environmentName string

@description('Azure region.')
param location string

@description('Workshop Storage Account resource ID (for Private Endpoint target).')
param storageAccountId string

// ---------------------------------------------------------------------------
// Derived values
// ---------------------------------------------------------------------------
var vnetName = 'vnet-workshop-${environmentName}'
var containerAppsSubnetName = 'snet-container-apps'
var privateEndpointSubnetName = 'snet-private-endpoints'
var privateEndpointName = 'pe-storage-table-${environmentName}'
var dnsZoneLinkName = 'link-${vnetName}'
var dnsZoneGroupName = 'dzg-storage-table'
// Private DNS Zone name for Azure Table Storage private endpoints.
// This is a DNS zone name, not a URL — linter false positive suppressed.
#disable-next-line no-hardcoded-env-urls
var privateDnsZoneName = 'privatelink.table.core.windows.net'

// ---------------------------------------------------------------------------
// Virtual Network
// ---------------------------------------------------------------------------
resource vnet 'Microsoft.Network/virtualNetworks@2024-01-01' = {
  name: vnetName
  location: location
  properties: {
    addressSpace: {
      addressPrefixes: ['10.0.0.0/16']
    }
    subnets: [
      {
        name: containerAppsSubnetName
        properties: {
          addressPrefix: '10.0.0.0/23'
          // Delegation required for Container Apps Environment VNet integration.
          // This subnet must be exclusively used by the CAE.
          delegations: [
            {
              name: 'Microsoft.App.environments'
              properties: {
                serviceName: 'Microsoft.App/environments'
              }
            }
          ]
        }
      }
      {
        name: privateEndpointSubnetName
        properties: {
          addressPrefix: '10.0.2.0/27'
          // Private endpoint network policies must be disabled to place a PE in this subnet.
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
    ]
  }
  tags: {
    project: 'workshop-portal'
    environment: environmentName
  }
}

// ---------------------------------------------------------------------------
// Private Endpoint — Table Storage
// ---------------------------------------------------------------------------
resource privateEndpoint 'Microsoft.Network/privateEndpoints@2024-01-01' = {
  name: privateEndpointName
  location: location
  properties: {
    subnet: {
      id: vnet.properties.subnets[1].id
    }
    privateLinkServiceConnections: [
      {
        name: privateEndpointName
        properties: {
          privateLinkServiceId: storageAccountId
          // 'table' targets the Table Storage sub-resource.
          // The app only uses Table Storage — no Blob or Queue endpoints needed.
          groupIds: ['table']
        }
      }
    ]
  }
  tags: {
    project: 'workshop-portal'
    environment: environmentName
  }
}

// ---------------------------------------------------------------------------
// Private DNS Zone
// ---------------------------------------------------------------------------
resource privateDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: privateDnsZoneName
  // Private DNS Zones are global resources (no location).
  location: 'global'
  tags: {
    project: 'workshop-portal'
    environment: environmentName
  }
}

// Link DNS Zone to the VNet so Container Apps can resolve private IPs.
resource dnsZoneVnetLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: privateDnsZone
  name: dnsZoneLinkName
  location: 'global'
  properties: {
    virtualNetwork: {
      id: vnet.id
    }
    registrationEnabled: false
  }
}

// DNS Zone Group: associates the private endpoint with the DNS Zone so that
// the storage account FQDN resolves to the private endpoint IP automatically.
resource dnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-01-01' = {
  parent: privateEndpoint
  name: dnsZoneGroupName
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'config-storage-table'
        properties: {
          privateDnsZoneId: privateDnsZone.id
        }
      }
    ]
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------
output containerAppsSubnetId string = vnet.properties.subnets[0].id
output privateEndpointSubnetId string = vnet.properties.subnets[1].id
output vnetId string = vnet.id
output privateEndpointName string = privateEndpoint.name
