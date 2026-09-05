// infra/main.bicep
// Minimal Azure resources for e2e testing.
// Creates: Storage Account + Function App (Consumption/Linux/Python, version
// selectable via the pythonVersion parameter, default 3.10).
// Optionally creates Application Insights (enableAppInsights=true).
//
// Usage:
//   az deployment group create -g <rg> -f infra/main.bicep \
//     -p functionAppName=<name> storageName=<name> location=<loc>

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Name of the Function App (must be globally unique).')
param functionAppName string

@description('Name of the Storage Account (3-24 lowercase alphanumeric).')
param storageName string

@description('Enable Application Insights (set true for logging e2e).')
param enableAppInsights bool = false

@description('Name of the Application Insights instance (used when enableAppInsights=true).')
param appInsightsName string = '${functionAppName}-ai'

@description('Python runtime version for the Linux Function App (e.g. 3.10, 3.13).')
param pythonVersion string = '3.10'

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

// ── Consumption Hosting Plan ───────────────────────────────────────────────
resource hostingPlan 'Microsoft.Web/serverfarms@2023-01-01' = {
  name: '${functionAppName}-plan'
  location: location
  sku: {
    name: 'Y1'
    tier: 'Dynamic'
  }
  kind: 'linux'
  properties: {
    reserved: true
  }
}

// ── Function App ───────────────────────────────────────────────────────────
resource functionApp 'Microsoft.Web/sites@2023-01-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp,linux'
  properties: {
    serverFarmId: hostingPlan.id
    siteConfig: {
      linuxFxVersion: 'Python|${pythonVersion}'
      appSettings: concat(
        [
          { name: 'AzureWebJobsStorage', value: storageConnectionString }
          { name: 'FUNCTIONS_EXTENSION_VERSION', value: '~4' }
          { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'python' }
          { name: 'SCM_DO_BUILD_DURING_DEPLOYMENT', value: 'true' }
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
    httpsOnly: true
  }
}

// ── Outputs ────────────────────────────────────────────────────────────────
output functionAppName string = functionApp.name
output defaultHostName string = functionApp.properties.defaultHostName
output appInsightsConnectionString string = enableAppInsights
  ? appInsights.properties.ConnectionString
  : ''
