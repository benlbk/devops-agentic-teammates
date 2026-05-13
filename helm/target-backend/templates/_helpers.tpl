{{- define "target-backend.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- define "target-backend.fullname" -}}
{{- if .Values.fullnameOverride }}{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}{{- printf "%s-%s" .Release.Name (default .Chart.Name .Values.nameOverride) | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- define "target-backend.labels" -}}
helm.sh/chart: {{ include "target-backend.name" . }}-{{ .Chart.Version }}
{{ include "target-backend.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}
{{- define "target-backend.selectorLabels" -}}
app.kubernetes.io/name: {{ include "target-backend.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
