import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useForm, Controller } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Plus, ArrowRight } from 'lucide-react';
import { toast } from 'react-hot-toast';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Textarea } from '@/components/ui/Textarea';
import { Dialog } from '@/components/ui/Dialog';
import { DataSourceBadge } from '@/components/common/DataSourceBadge';
import { useAppMode } from '@/context/AppModeContext';
import { createProject } from '@/lib/aurumApi';
import { cn } from '@/utils/cn';
import type { Environment, NewProjectFormValues } from '@/types';

const INITIAL_DOMAINS = ['Retail', 'Finance', 'Healthcare', 'Other'];
const ENVIRONMENTS: Environment[] = ['Development', 'QA', 'Production'];

const schema = z.object({
  name: z.string().min(2, 'Project name must be at least 2 characters').max(60),
  businessDomain: z.string().min(1, 'Please select a business domain'),
  description: z.string().max(500).optional(),
  environment: z.enum(['Development', 'QA', 'Production']),
});

type FormValues = z.infer<typeof schema>;

export function NewProjectPage() {
  const navigate = useNavigate();
  const { displayMode } = useAppMode();
  const [domains, setDomains] = useState<string[]>(INITIAL_DOMAINS);
  const [showDomainDialog, setShowDomainDialog] = useState(false);
  const [newDomain, setNewDomain] = useState('');
  const [newDomainError, setNewDomainError] = useState('');

  const {
    register,
    handleSubmit,
    control,
    watch,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: '',
      businessDomain: '',
      description: '',
      environment: 'Development',
    },
  });

  const selectedDomain = watch('businessDomain');
  const selectedEnv = watch('environment');

  function handleAddDomain() {
    const trimmed = newDomain.trim();
    if (!trimmed) {
      setNewDomainError('Domain name cannot be empty.');
      return;
    }
    if (domains.map((d) => d.toLowerCase()).includes(trimmed.toLowerCase())) {
      setNewDomainError('This domain already exists.');
      return;
    }
    setDomains((prev) => [...prev.filter((d) => d !== 'Other'), trimmed, 'Other']);
    setValue('businessDomain', trimmed);
    setNewDomain('');
    setNewDomainError('');
    setShowDomainDialog(false);
    toast.success(`Domain "${trimmed}" added`);
  }

  async function onSubmit(data: FormValues) {
    try {
      const project = await createProject({
        name: data.name,
        description: data.description ?? '',
        environment: data.environment,
      });
      toast.success(`Project "${project.name}" created.`);
      navigate(`/projects/${project.id}/connect`);
    } catch {
      toast.error('Could not create project. Check that the API is running.');
    }
  }

  return (
    <div className="min-h-full flex items-start justify-center px-4 py-12 animate-fade-in">
      <div className="w-full max-w-lg">
        {/* Page Header */}
        <div className="mb-8">
          <div className="flex flex-wrap items-center gap-3 mb-2">
            <h2 className="text-2xl font-bold text-[#f1f5f9]">Create Project</h2>
            <DataSourceBadge mode={displayMode} />
          </div>
          <p className="mt-1 text-sm text-[#6b7280]">
            Define the project identity before connecting any data source.
          </p>
        </div>

        {/* Form Card */}
        <div className="rounded-xl border border-[#252637] bg-[#13141e] p-6">
          <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-6">
            {/* Project Name */}
            <Input
              label="Project Name"
              placeholder="e.g. Retail Analytics"
              error={errors.name?.message}
              {...register('name')}
            />

            {/* Business Domain */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold uppercase tracking-widest text-[#6b7280]">
                  Business Domain
                </span>
                <button
                  type="button"
                  onClick={() => {
                    setNewDomain('');
                    setNewDomainError('');
                    setShowDomainDialog(true);
                  }}
                  className="flex items-center gap-1 text-xs text-[#6366f1] hover:text-[#4f46e5] transition-colors focus:outline-none focus:underline"
                >
                  <Plus size={12} />
                  Add Domain
                </button>
              </div>
              <Controller
                name="businessDomain"
                control={control}
                render={({ field }) => (
                  <div className="flex flex-wrap gap-2" role="group" aria-label="Business domain">
                    {domains.map((domain) => (
                      <button
                        type="button"
                        key={domain}
                        onClick={() => field.onChange(domain)}
                        aria-pressed={field.value === domain}
                        className={cn(
                          'rounded-lg border px-3 py-1.5 text-sm font-medium transition-all duration-150 focus:outline-none focus:ring-2 focus:ring-[#6366f1]',
                          field.value === domain
                            ? 'border-[#6366f1] bg-[#6366f1]/15 text-[#6366f1]'
                            : 'border-[#252637] bg-[#1a1b28] text-[#94a3b8] hover:border-[#6366f1]/30 hover:text-[#f1f5f9]'
                        )}
                      >
                        {domain}
                      </button>
                    ))}
                  </div>
                )}
              />
              {errors.businessDomain && (
                <p className="text-xs text-[#ef4444]" role="alert">
                  {errors.businessDomain.message}
                </p>
              )}
            </div>

            {/* Description */}
            <Textarea
              label="Description"
              placeholder="Describe what this project validates..."
              rows={4}
              error={errors.description?.message}
              {...register('description')}
            />

            {/* Environment */}
            <div className="space-y-2">
              <span className="text-xs font-semibold uppercase tracking-widest text-[#6b7280]">
                Environment
              </span>
              <Controller
                name="environment"
                control={control}
                render={({ field }) => (
                  <div className="flex flex-wrap gap-2" role="group" aria-label="Environment">
                    {ENVIRONMENTS.map((env) => (
                      <button
                        type="button"
                        key={env}
                        onClick={() => field.onChange(env)}
                        aria-pressed={field.value === env}
                        className={cn(
                          'rounded-lg border px-3 py-1.5 text-sm font-medium transition-all duration-150 focus:outline-none focus:ring-2 focus:ring-[#6366f1]',
                          field.value === env
                            ? 'border-[#6366f1] bg-[#6366f1]/15 text-[#6366f1]'
                            : 'border-[#252637] bg-[#1a1b28] text-[#94a3b8] hover:border-[#6366f1]/30 hover:text-[#f1f5f9]'
                        )}
                      >
                        {env}
                      </button>
                    ))}
                  </div>
                )}
              />
            </div>

            {/* Form Actions */}
            <div className="flex items-center justify-end gap-3 pt-2 border-t border-[#252637]">
              <Button
                type="button"
                variant="secondary"
                onClick={() => navigate('/')}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                variant="primary"
                isLoading={isSubmitting}
                rightIcon={<ArrowRight size={16} />}
              >
                Create Project
              </Button>
            </div>
          </form>
        </div>
      </div>

      {/* Add Domain Dialog */}
      <Dialog
        open={showDomainDialog}
        onClose={() => setShowDomainDialog(false)}
        title="Add Business Domain"
        description="Enter a new domain to add to the selection list."
      >
        <div className="space-y-4">
          <div className="space-y-1.5">
            <label htmlFor="new-domain-input" className="text-xs font-semibold uppercase tracking-widest text-[#6b7280]">
              Domain Name
            </label>
            <input
              id="new-domain-input"
              type="text"
              value={newDomain}
              onChange={(e) => {
                setNewDomain(e.target.value);
                setNewDomainError('');
              }}
              onKeyDown={(e) => e.key === 'Enter' && handleAddDomain()}
              placeholder="e.g. Manufacturing"
              autoFocus
              className="w-full rounded-lg border border-[#252637] bg-[#1a1b28] px-3 py-2.5 text-sm text-[#f1f5f9] placeholder:text-[#4b5563] transition-colors focus:border-[#6366f1] focus:ring-1 focus:ring-[#6366f1] focus:outline-none"
              aria-describedby={newDomainError ? 'domain-error' : undefined}
            />
            {newDomainError && (
              <p id="domain-error" className="text-xs text-[#ef4444]" role="alert">
                {newDomainError}
              </p>
            )}
          </div>
          <div className="flex justify-end gap-3">
            <Button variant="secondary" onClick={() => setShowDomainDialog(false)}>
              Cancel
            </Button>
            <Button variant="primary" onClick={handleAddDomain} leftIcon={<Plus size={14} />}>
              Add Domain
            </Button>
          </div>
        </div>
      </Dialog>
    </div>
  );
}
