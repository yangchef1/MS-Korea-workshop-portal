# ARM Templates for Azure Workshop Portal

This directory contains Azure Resource Manager (ARM) templates that can be deployed to workshop participant resource groups.

## Available Templates

### 1. vnet-basic.json
A simple virtual network template suitable for basic networking workshops.

**Resources:**
- Virtual Network (10.0.0.0/16)
- One subnet (10.0.1.0/24)

**Use cases:**
- Basic networking concepts
- Simple Azure networking workshops
- Foundation for adding more resources

### 2. vnet-advanced.json
An advanced networking setup with multiple subnets, NSG, and storage.

**Resources:**
- Virtual Network (10.1.0.0/16)
- Three subnets (web, app, data)
- Network Security Group with HTTP/HTTPS/SSH rules
- Storage Account (Standard_LRS)

**Use cases:**
- Multi-tier application workshops
- Network segmentation training
- Storage integration workshops

### 3. compute-basic.json
A complete compute environment with VNet and Linux VM.

**Resources:**
- Virtual Network
- Linux VM (Ubuntu 22.04 LTS)
- Public IP
- Network Interface
- Network Security Group (SSH access)

**Use cases:**
- VM deployment workshops
- Linux administration training
- Application deployment workshops

## Deployment

These templates are automatically deployed by the Azure Workshop Portal when creating a new workshop. Participants receive pre-configured resource groups with the selected template already deployed.

## Customization

To add new templates:

1. Create a new ARM template JSON file in this directory
2. Upload it to Azure Blob Storage under `templates/` folder
3. The template will automatically appear in the workshop creation form

## Parameters

All templates support standard Azure parameters:
- `location`: Azure region (inherited from resource group)
- Template-specific parameters with sensible defaults

## Outputs

Each template provides useful outputs that can be displayed to workshop participants, such as:
- Resource IDs
- Connection strings
- Access information

## Best Practices

1. Use parameter defaults for ease of use
2. Include descriptive metadata
3. Minimize cost with appropriate SKUs (B-series VMs, Standard_LRS storage)
4. Always enable HTTPS for storage accounts
5. Tag resources appropriately
