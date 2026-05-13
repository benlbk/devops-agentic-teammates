{{- define "target-frontend.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- define "target-frontend.fullname" -}}
{{- if .Values.fullnameOverride }}{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}{{- printf "%s-%s" .Release.Name (default .Chart.Name .Values.nameOverride) | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- define "target-frontend.labels" -}}
helm.sh/chart: {{ include "target-frontend.name" . }}-{{ .Chart.Version }}
{{ include "target-frontend.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}
{{- define "target-frontend.selectorLabels" -}}
app.kubernetes.io/name: {{ include "target-frontend.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
