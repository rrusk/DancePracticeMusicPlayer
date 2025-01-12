In Kivy, the `background_color` is multiplied by a default texture's pixel values rather than directly rendering the raw
RGB equivalent. For instance, suppose **default gray texture** in Kivy is a solid mid-gray with RGBA values of
`(0.35, 0.35, 0.35, 1)`.

Then when `background_color=(0.2, 0.6, 0.8, 1)` is applied, each channel of the default texture's color is multiplied by
the corresponding component of `background_color`.

### Calculation:
Default texture color: (0.35, 0.35, 0.35, 1)
Provided `background_color`: (0.2, 0.6, 0.8, 1)

For each channel (Red, Green, Blue, Alpha):
1. **Red**: ( 0.35 x 0.2 = 0.07 )
2. **Green**: ( 0.35 x 0.6 = 0.21 )
3. **Blue**: ( 0.35 x 0.8 = 0.28 )
4. **Alpha**: ( 1 x 1 = 1 ) (unchanged)

Normalized RGBA values: ( 0.07, 0.21, 0.28, 1 )

### Converting to Standard RGB (0–255):
1. **Red**: ( 0.07 x 255 = 17.85 ) → ( 18 ) (rounded)
2. **Green**: ( 0.21 x 255 = 53.55 ) → ( 54 ) (rounded)
3. **Blue**: ( 0.28 x 255 = 71.4 ) -> ( 71 ) (rounded)  
4. **Alpha**: ( 1 x 255 = 255 )

### Final Result:
**RGB:** ( 18, 54, 71 )  
**RGBA:** (18, 54, 71, 255)

In fact, the Ubuntu utility gpick was used to match the background color to the text button with "rgb(18,53,70)"
