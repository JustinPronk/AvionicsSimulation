#include <stdio.h>
#include <Hal.h>
#include <kalman.h>

KalmanState kf;


void setup() {
  HAL_Init();
  printf("[main] HAL initialised, waiting for data...\n");
}

void loop() {
  HAL_Update();

  float altitude_from_baro = HAL_ReadAlt();

  kalman_predict(kf);
  kalman_update(kf, altitude_from_baro);

  //printf("RAW alt: %.2f | KF alt: %.2f | KF vel: %.2f | triggered: %d\n",
  //  altitude_from_baro, kf.altitude, kf.velocity, kf.apogee_triggered);


  if (check_apogee(kf)) {
    printf(">>> APOGEE DETECTED at altitude %.2f m\n", kf.altitude);
    HAL_SendEvent("APOGEE", kf.altitude);

    HAL_FirePyro1(kf.altitude);
    printf(">>> PYRO 1 FIRED at altiude %.2f m\n", kf.altitude);
  }

  // printf("Alt(est): %.2f | Vel(est): %.2f\n", kf.altitude, kf.velocity);
}

