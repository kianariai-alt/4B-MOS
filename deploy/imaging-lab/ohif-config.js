window.config = {
  routerBasename: '/',
  showStudyList: true,
  showWarningMessageForCrossOrigin: true,
  showCPUFallbackMessage: true,
  showLoadingIndicator: true,
  extensions: [],
  modes: [],
  defaultDataSourceName: 'synthetic-orthanc',
  dataSources: [{
    namespace: '@ohif/extension-default.dataSourcesModule.dicomweb',
    sourceName: 'synthetic-orthanc',
    configuration: {
      friendlyName: '4B-MOS synthetic data only',
      name: 'synthetic-orthanc',
      wadoUriRoot: window.location.origin + '/wado',
      qidoRoot: window.location.origin + '/dicom-web',
      wadoRoot: window.location.origin + '/dicom-web',
      qidoSupportsIncludeField: true,
      imageRendering: 'wadors',
      thumbnailRendering: 'wadors',
      enableStudyLazyLoad: true,
      supportsFuzzyMatching: false,
      supportsWildcard: false,
      singlepart: 'bulkdata,video,pdf',
      dicomUploadEnabled: false,
      bulkDataURI: { enabled: true, relativeResolution: 'studies' }
    }
  }]
};
