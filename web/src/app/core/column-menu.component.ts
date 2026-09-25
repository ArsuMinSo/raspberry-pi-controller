import { Component, input } from '@angular/core';
import { IonButton, IonCheckbox, IonIcon, IonItem, IonLabel, IonList, IonPopover } from '@ionic/angular';
import { addIcons } from 'ionicons';
import { optionsOutline } from 'ionicons/icons';

import { TableColumns } from './table-columns';

/** Button + popover to show/hide a table's columns. Drop one into each table's toolbar. */
@Component({
  selector: 'app-column-menu',
  template: `
    <ion-button [id]="triggerId()" fill="clear" size="small" aria-label="Show/hide columns">
      <ion-icon slot="icon-only" name="options-outline"></ion-icon>
    </ion-button>
    <ion-popover [trigger]="triggerId()" [dismissOnSelect]="false">
      <ng-template>
        <ion-list lines="full">
          @for (d of cols().defs; track d.key) {
            <ion-item>
              <ion-checkbox slot="start" [checked]="cols().isVisible(d.key)" (ionChange)="cols().toggle(d.key)"
                            [disabled]="cols().isVisible(d.key) && cols().visible().size === 1"></ion-checkbox>
              <ion-label>{{ d.label }}</ion-label>
            </ion-item>
          }
          <ion-item button detail="false" (click)="cols().reset()">
            <ion-label color="medium">Reset columns</ion-label>
          </ion-item>
        </ion-list>
      </ng-template>
    </ion-popover>
  `,
  imports: [IonButton, IonIcon, IonPopover, IonList, IonItem, IonCheckbox, IonLabel],
})
export class ColumnMenuComponent {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  readonly cols = input.required<TableColumns<any>>();
  /** Unique per table instance on the page — ion-popover triggers must be unique DOM ids. */
  readonly triggerId = input.required<string>();

  constructor() {
    addIcons({ optionsOutline });
  }
}
