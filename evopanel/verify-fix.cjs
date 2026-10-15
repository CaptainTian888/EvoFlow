const fs = require('fs');
const sci = fs.readFileSync('src/style/sci-fi-theme.css', 'utf8');
const surf = fs.readFileSync('src/style/theme-surfaces.css', 'utf8');

const reUnguardedConfig = /^\.config-section \.form-input,/gm;
const reUnguardedModels = /^\.models-edit-modal-body \.form-input,/gm;
const reGatedConfig = /:where\(html\[data-scifi-ui='1'\]\) \.config-section/g;
const reGatedModels = /:where\(html\[data-scifi-ui='1'\]\) \.models-edit-modal-body/g;
const reDarkConfig = /data-theme='dark'\] \.config-section/g;
const reLightConfig = /data-theme="light"\] \.config-section/g;
const reDarkMedia = /data-theme='dark'\] \.media-vendor-form/g;
const reDarkPane = /data-theme='dark'\] \.settings-modal-pane/g;

const out = {
  unguardedConfigSection: (sci.match(reUnguardedConfig) || []).length,
  unguardedModelsEdit: (sci.match(reUnguardedModels) || []).length,
  gatedConfigSectionRules: (sci.match(reGatedConfig) || []).length,
  gatedModelsEditRules: (sci.match(reGatedModels) || []).length,
  darkConfigSectionRules: (surf.match(reDarkConfig) || []).length,
  lightConfigSectionRules: (surf.match(reLightConfig) || []).length,
  darkMediaVendorFormRules: (surf.match(reDarkMedia) || []).length,
  darkSettingsModalPaneRules: (surf.match(reDarkPane) || []).length,
};
console.log(JSON.stringify(out, null, 2));
