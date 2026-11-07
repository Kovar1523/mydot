const char *colorname[] = {

  /* 8 normal colors */
  [0] = "#0c161d", /* black   */
  [1] = "#128590", /* red     */
  [2] = "#127ebb", /* green   */
  [3] = "#0F9073", /* yellow  */
  [4] = "#226eff", /* blue    */
  [5] = "#1379d6", /* magenta */
  [6] = "#0e7dc5", /* cyan    */
  [7] = "#c2c4c6", /* white   */

  /* 8 bright colors */
  [8]  = "#6c7984",  /* black   */
  [9]  = "#128590",  /* red     */
  [10] = "#127ebb", /* green   */
  [11] = "#0F9073", /* yellow  */
  [12] = "#226eff", /* blue    */
  [13] = "#1379d6", /* magenta */
  [14] = "#0e7dc5", /* cyan    */
  [15] = "#c2c4c6", /* white   */

  /* special colors */
  [256] = "#0c161d", /* background */
  [257] = "#c2c4c6", /* foreground */
  [258] = "#c2c4c6",     /* cursor */
};

/* Default colors (colorname index)
 * foreground, background, cursor */
 unsigned int defaultbg = 0;
 unsigned int defaultfg = 257;
 unsigned int defaultcs = 258;
 unsigned int defaultrcs= 258;
