<template>
  <div class="overlay" @mousedown.self="overlayDown = true" @mouseup="overlayUp">
    <div class="dialog">

      <div class="dialog-header">
        <span class="dialog-title">Confirm {{ actionLabel }} — {{ target.toUpperCase() }}</span>
        <button class="dialog-close" @click="$emit('cancel')" aria-label="Close">×</button>
      </div>

      <div class="dialog-body">
        <p class="lede">{{ plan.lede }}</p>

        <!-- Architecture preview (ECS/EKS) — reuses the diagrams/ PNGs; the full
             zoom/pan viewer is one click away via ArchitectureDialog. -->
        <div v-if="diagramKey" class="arch-preview">
          <img
            v-if="!imgFailed"
            :src="`/architecture/${diagramKey}-architecture.png`"
            :alt="`${target.toUpperCase()} architecture diagram`"
            class="arch-thumb"
            @error="imgFailed = true"
            @click="showArchitecture = true"
          />
          <button class="arch-open" @click="showArchitecture = true">
            View full architecture ↗
          </button>
        </div>

        <div class="section-label">Resources about to be {{ pastTense }}</div>
        <ul class="resource-list">
          <li v-for="r in plan.resources" :key="r">{{ r }}</li>
        </ul>

        <div class="warning" :class="{ 'warning--light': plan.light }">
          <span class="warning-icon">⚠</span>
          <span>{{ plan.warning }}</span>
        </div>

        <label class="ack-label">
          <input type="checkbox" v-model="acknowledged" />
          {{ plan.ack }}
        </label>
      </div>

      <div class="dialog-footer">
        <button class="btn-cancel" @click="$emit('cancel')">Cancel</button>
        <button
          class="btn-confirm"
          :class="{ 'btn-confirm--destroy': action === 'destroy' }"
          :disabled="!acknowledged"
          @click="$emit('confirm')"
        >
          {{ actionLabel }} {{ target.toUpperCase() }}
        </button>
      </div>

    </div>

    <!-- Full architecture viewer, reused as-is from the Home view. -->
    <ArchitectureDialog
      v-if="showArchitecture"
      :deployment-type="diagramKey"
      @close="showArchitecture = false"
    />
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import ArchitectureDialog from './ArchitectureDialog.vue'

const props = defineProps({
  target: { type: String, required: true },       // 's3' | 'ecs' | 'eks'
  action: { type: String, default: 'deploy' },     // 'deploy' | 'destroy'
})
const emit = defineEmits(['confirm', 'cancel'])
// Backdrop dismiss only on a full click that starts AND ends on the overlay —
// a text-selection drag that escapes the panel fires click.self too (the
// click lands on the elements' common ancestor), and must not close it.
const overlayDown = ref(false)
function overlayUp(e) {
  if (overlayDown.value && e.target === e.currentTarget) emit('cancel')
  overlayDown.value = false
}

const acknowledged   = ref(false)
const showArchitecture = ref(false)
const imgFailed      = ref(false)

// 'eks'/'ecs' have deployment-specific diagrams; S3 has none.
const diagramKey = computed(() =>
  props.target === 'ecs' || props.target === 'eks' ? props.target : '')

const actionLabel = computed(() => props.action === 'destroy' ? 'Destroy' : 'Deploy')
const pastTense   = computed(() => props.action === 'destroy' ? 'destroyed' : 'created')

// Per-target pre-flight plans. Deploy is the heavyweight path (itemized create +
// cost/time warning); destroy reframes the same resources as being torn down.
const PLANS = {
  ecs: {
    lede: 'This provisions the full ECS Fargate stack (CloudFormation stack “NceStack”).',
    resources: [
      'VPC with public/private subnets and NAT',
      'ECS Fargate cluster + service (task: app container)',
      'Application Load Balancer (public entry point)',
      'EFS file system (config, reports, interactive, Quarto site)',
      'CloudFront distribution (HTTPS front door)',
      'CloudWatch log group',
      'Amazon Managed Grafana workspace (when enabled)',
      'Pulls the app image from the shared ECR repository (deploy ECR first)',
    ],
  },
  eks: {
    lede: 'This provisions the full EKS stack (CloudFormation stack “NceEksStack”).',
    resources: [
      'VPC with public/private subnets and NAT',
      'EKS cluster + managed node group (EC2 nodes)',
      'AWS Load Balancer Controller → Application Load Balancer',
      'EFS file system + access points (config, reports, interactive, Quarto)',
      'CloudFront distribution (HTTPS front door)',
      'IAM roles for service accounts (IRSA)',
      'Amazon Managed Grafana workspace (when enabled)',
      'Pulls the app image from the shared ECR repository (deploy ECR first)',
    ],
  },
  ecr: {
    light: true,
    lede: 'This creates the shared container-image registry and pushes the app image.',
    resources: [
      'ECR repository (shared — ECS and EKS pull from it)',
      'Container image build + push (:latest) — requires Docker on the server',
    ],
    warning: 'The image build+push runs on the server\'s Docker daemon and can take several minutes.',
    ack: 'I understand this creates the ECR repository and pushes an image.',
    destroyLede: 'This deletes the ECR repository and every image in it.',
    destroyWarning: 'ECS and EKS pull from this repository: they cannot deploy (and their tasks/pods cannot restart) until ECR is republished. Deleted images cannot be recovered.',
  },
  s3: {
    light: true,
    lede: 'This publishes the static assets bundle to S3.',
    resources: [
      'S3 bucket (region: account default)',
      'Objects uploaded under the configured prefix',
    ],
    warning: 'Objects may be publicly readable depending on the bucket policy — confirm the bucket and its exposure before publishing.',
    ack: 'I understand this writes to the S3 bucket.',
  },
}

const plan = computed(() => {
  const base = PLANS[props.target] || PLANS.s3
  // Deploy vs destroy share the resource list but differ in tone/warning.
  if (props.action === 'destroy') {
    return {
      ...base,
      lede: base.destroyLede
        || (base.light
          ? 'This removes the published assets from S3.'
          : `This tears down every resource in ${base.lede.match(/“[^”]+”/)?.[0] || 'the stack'} — data on EFS is deleted.`),
      warning: base.destroyWarning
        || (base.light
          ? 'Deleted objects cannot be recovered.'
          : 'Destroying the stack is irreversible: EFS data (reports, config, interactive site) is deleted and the public URL stops resolving.'),
      ack: 'I understand this permanently destroys the resources above.',
    }
  }
  return {
    warning: base.light
      ? base.warning
      : 'This is a long-running operation (10–25 min) that creates billable AWS resources. Leave the job running — it survives a page refresh.',
    ack: base.ack || 'I understand this creates billable AWS resources.',
    ...base,
  }
})
</script>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 200;
}

.dialog {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  width: 540px;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
}

.dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.85rem 1rem 0.75rem;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.dialog-title { font-size: 0.95rem; font-weight: 600; color: var(--text-1); }
.dialog-close {
  background: none; border: none;
  color: var(--text-3); cursor: pointer; font-size: 1.4rem; line-height: 1;
}
.dialog-close:hover { color: var(--text-1); }

.dialog-body {
  padding: 0.85rem 1rem;
  overflow-y: auto;
}
.lede { margin: 0 0 0.75rem; color: var(--text-1); font-size: 0.88rem; line-height: 1.4; }

.arch-preview {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.35rem;
  margin-bottom: 0.85rem;
}
.arch-thumb {
  max-width: 100%;
  max-height: 220px;
  border: 1px solid var(--border);
  border-radius: 4px;
  cursor: zoom-in;
  background: var(--surface-alt);
}
.arch-open {
  background: none;
  border: none;
  color: var(--action);
  cursor: pointer;
  font-size: 0.8rem;
  padding: 0;
}
.arch-open:hover { text-decoration: underline; }

.section-label {
  font-size: 0.72rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-3);
  margin: 0.4rem 0 0.35rem;
}
.resource-list {
  margin: 0 0 0.85rem;
  padding-left: 1.15rem;
  color: var(--text-2);
  font-size: 0.83rem;
  line-height: 1.5;
}

.warning {
  display: flex;
  gap: 0.5rem;
  align-items: flex-start;
  padding: 0.6rem 0.75rem;
  border-radius: 5px;
  background: var(--badge-run-bg, rgba(220, 130, 20, 0.12));
  color: var(--text-1);
  font-size: 0.82rem;
  line-height: 1.4;
  margin-bottom: 0.85rem;
}
.warning--light { background: rgba(120, 120, 120, 0.12); }
.warning-icon { flex-shrink: 0; }

.ack-label {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  cursor: pointer;
  color: var(--text-1);
  font-size: 0.85rem;
}
.ack-label input { cursor: pointer; flex-shrink: 0; }

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 0.6rem;
  padding: 0.75rem 1rem;
  border-top: 1px solid var(--border);
  flex-shrink: 0;
}
.btn-cancel {
  padding: 6px 16px;
  background: transparent;
  border: 1px solid var(--border);
  border-radius: 5px;
  color: var(--text-2);
  cursor: pointer;
  font-size: 0.85rem;
}
.btn-cancel:hover { border-color: var(--text-2); color: var(--text-1); }
.btn-confirm {
  padding: 6px 16px;
  background: var(--action);
  border: none;
  border-radius: 5px;
  color: #fff;
  cursor: pointer;
  font-size: 0.85rem;
  transition: background 0.15s;
}
.btn-confirm:disabled { background: var(--action-off); color: var(--action-off-text); cursor: not-allowed; }
.btn-confirm:not(:disabled):hover { background: var(--action-hover); }
.btn-confirm--destroy { background: #b1442f; }
.btn-confirm--destroy:not(:disabled):hover { background: #963824; }

@media (max-width: 768px) {
  .overlay { padding: 0; }
  .dialog {
    width: 100vw;
    max-width: none;
    height: 100vh;
    height: 100dvh;
    max-height: none;
    border-radius: 0;
  }
}
</style>
