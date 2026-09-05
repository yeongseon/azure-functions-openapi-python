// infra/main.bicep
// Minimal Azure resources for e2e testing.
// Creates: Storage Account + Function App on a Flex Consumption (FC1) plan,
// Linux/Python, version selectable via the pythonVersion parameter (default 3.10).
// Optionally creates Application Insights (enableAppInsights=true).
//
// Flex Consumption (not the classic Y1 Consumption plan) is required because
// Python 3.13+ is only available on Flex Consumption / Premium / Dedicated —
// the classic Linux Consumption plan tops out at Python 3.12.
// See https://learn.microsoft.com/azure/azure-functions/functions-versions?pivots=programming-language-python
//
// Usage:
//   az deployment group create -g <rg> -f infra/main.bicep \
//     -p functionAppName=<name> storageName=<name> location=<loc> pythonVersion=3.13

@description('Azure region for all resources (must support Flex Consumption).')
param location string = resourceGroup().location

@description('Name of the Function App (must be globally unique).')
param functionAppName string

@description('Name of the Storage Account (3-24 lowercase alphanumeric).')
param storageName string

@description('Enable Application Insights (set true for logging e2e).')
param enableAppInsights bool = false

@description('Name of the Application Insights instance (used when enableAppInsights=true).')
param appInsightsName string = '${functionAppName}-ai'

@description('Python runtime version for the Flex Consumption Function App (e.g. 3.10, 3.13).')
param pythonVersion string = '3.10'

@description('Per-instance memory (MB) for the Flex Consumption app.')
param instanceMemoryMB int = 2048

@description('Maximum number of instances the app can scale out to (Flex minimum is 40).')
param maximumInstanceCount int = 40

// Name of the blob container that holds the deployment (.zip) package.
var deploymentContainerName = 'app-package'

// ── Storage Account ────────────────────────────────────────────────────────
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageName
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' = {
  parent: storageAccount
  name: 'default'
}

// Deployment package container required by the Flex Consumption plan.
resource deploymentContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: blobService
  name: deploymentContainerName
}

var storageConnectionString = 'DefaultEndpointsProtocol=https;AccountName=${storageAccount.name};EndpointSuffix=${environment().suffixes.storage};AccountKey=${storageAccount.listKeys().keys[0].value}'

// ── App Insights (optional) ────────────────────────────────────────────────
resource appInsights 'Microsoft.Insights/components@2020-02-02' = if (enableAppInsights) {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    RetentionInDays: 30
  }
}

// ── Flex Consumption Hosting Plan ──────────────────────────────────────────
resource hostingPlan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: '${functionAppName}-plan'
  location: location
  sku: {
    name: 'FC1'
    tier: 'FlexConsumption'
  }
  kind: 'functionapp'
  properties: {
    reserved: true
  }
}

// ── Function App (Flex Consumption) ────────────────────────────────────────
resource functionApp 'Microsoft.Web/sites@2024-04-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp,linux'
  dependsOn: [ deploymentContainer ]
  properties: {
    serverFarmId: hostingPlan.id
    httpsOnly: true
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${storageAccount.properties.primaryEndpoints.blob}${deploymentContainerName}'
          authentication: {
            type: 'StorageAccountConnectionString'
            storageAccountConnectionStringName: 'DEPLOYMENT_STORAGE_CONNECTION_STRING'
          }
        }
      }
      scaleAndConcurrency: {
        instanceMemoryMB: instanceMemoryMB
        maximumInstanceCount: maximumInstanceCount
      }
      runtime: {
        name: 'python'
        version: pythonVersion
      }
    }
    siteConfig: {
      appSettings: concat(
        [
          { name: 'AzureWebJobsStorage', value: storageConnectionString }
          { name: 'DEPLOYMENT_STORAGE_CONNECTION_STRING', value: storageConnectionString }
        ],
        enableAppInsights
          ? [
              {
                name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
                value: appInsights.properties.ConnectionString
              }
            ]
          : []
      )
    }
  }
}

// ── Outputs ────────────────────────────────────────────────────────────────
output functionAppName string = functionApp.name
output defaultHostName string = functionApp.properties.defaultHostName
output appInsightsConnectionString string = enableAppInsights
  ? appInsights.properties.ConnectionString
  : ''
