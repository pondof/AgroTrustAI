import { sha3_256 } from "js-sha3";
import { Loader2, Plus } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { toast } from "sonner";

import { extractErrorMessage } from "@/api/client";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useCreateDossie } from "@/hooks/useDossies";
import { useAuth } from "@/hooks/useAuth";
import type { SubscriptionRequest } from "@/types";

const PURPOSES = ["custeio", "investimento", "comercialização"];

interface FormState {
  cpf: string;
  car_number: string;
  property_area_ha: string;
  latitude: string;
  longitude: string;
  municipio: string;
  estado: string;
  biome: string;
  credit_amount_brl: string;
  credit_purpose: string;
}

const EMPTY: FormState = {
  cpf: "",
  car_number: "",
  property_area_ha: "",
  latitude: "",
  longitude: "",
  municipio: "",
  estado: "",
  biome: "",
  credit_amount_brl: "",
  credit_purpose: "custeio",
};

export function NewDossieModal() {
  const { session } = useAuth();
  const mutation = useCreateDossie();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<FormState>(EMPTY);

  const set = (key: keyof FormState, value: string) => setForm((f) => ({ ...f, [key]: value }));

  const cpfDigits = form.cpf.replace(/\D/g, "");
  const cpfValid = cpfDigits.length === 11;

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!cpfValid) {
      toast.error("Informe um CPF com 11 dígitos.");
      return;
    }
    // O CPF é convertido em hash SHA-3-256 localmente — o CPF em claro NUNCA é enviado.
    const producer_cpf_hash = sha3_256(cpfDigits);
    const body: SubscriptionRequest = {
      producer_cpf_hash,
      car_number: form.car_number,
      property_area_ha: Number.parseFloat(form.property_area_ha),
      location: {
        latitude: Number.parseFloat(form.latitude),
        longitude: Number.parseFloat(form.longitude),
        municipio: form.municipio,
        estado: form.estado.toUpperCase(),
        biome: form.biome || null,
      },
      credit_amount_brl: Number.parseFloat(form.credit_amount_brl),
      credit_purpose: form.credit_purpose,
      requested_by: session?.username ?? "desconhecido",
    };
    mutation.mutate(body, {
      onSuccess: (res) => {
        toast.success(`Dossiê ${res.dossie_id} iniciado.`);
        setForm(EMPTY);
        setOpen(false);
      },
      onError: (error) => toast.error(extractErrorMessage(error, "Falha ao criar o dossiê.")),
    });
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button className="gap-2">
          <Plus className="h-4 w-4" /> Novo Dossiê
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Novo Dossiê de Subscrição</DialogTitle>
          <DialogDescription>
            O CPF é convertido em hash localmente (SHA-3-256); o CPF em claro não é transmitido.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="CPF do produtor" required>
              <Input
                inputMode="numeric"
                placeholder="000.000.000-00"
                value={form.cpf}
                onChange={(e) => set("cpf", e.target.value)}
                aria-invalid={form.cpf.length > 0 && !cpfValid}
              />
            </Field>
            <Field label="Número do CAR" required>
              <Input value={form.car_number} onChange={(e) => set("car_number", e.target.value)} required />
            </Field>
            <Field label="Área (ha)" required>
              <Input
                type="number"
                step="0.01"
                min="0.01"
                value={form.property_area_ha}
                onChange={(e) => set("property_area_ha", e.target.value)}
                required
              />
            </Field>
            <Field label="Valor do crédito (R$)" required>
              <Input
                type="number"
                step="0.01"
                min="0.01"
                value={form.credit_amount_brl}
                onChange={(e) => set("credit_amount_brl", e.target.value)}
                required
              />
            </Field>
            <Field label="Latitude" required>
              <Input
                type="number"
                step="any"
                value={form.latitude}
                onChange={(e) => set("latitude", e.target.value)}
                required
              />
            </Field>
            <Field label="Longitude" required>
              <Input
                type="number"
                step="any"
                value={form.longitude}
                onChange={(e) => set("longitude", e.target.value)}
                required
              />
            </Field>
            <Field label="Município" required>
              <Input value={form.municipio} onChange={(e) => set("municipio", e.target.value)} required />
            </Field>
            <Field label="UF" required>
              <Input
                maxLength={2}
                value={form.estado}
                onChange={(e) => set("estado", e.target.value)}
                placeholder="MT"
                required
              />
            </Field>
            <Field label="Bioma">
              <Input value={form.biome} onChange={(e) => set("biome", e.target.value)} placeholder="Cerrado" />
            </Field>
            <Field label="Finalidade" required>
              <select
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                value={form.credit_purpose}
                onChange={(e) => set("credit_purpose", e.target.value)}
              >
                {PURPOSES.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </Field>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancelar
            </Button>
            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Iniciar dossiê
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function Field({ label, required, children }: { label: string; required?: boolean; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label>
        {label} {required && <span className="text-destructive">*</span>}
      </Label>
      {children}
    </div>
  );
}
