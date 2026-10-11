module permuted_decoder_sharing(
    input  [2:0]  sel,
    input  [31:0] data,
    output reg [3:0] y,
    output reg [3:0] z
);
    always @* begin
        y = 0;
        case (sel)
            3'd0: y = data[0  +: 4];
            3'd1: y = data[4  +: 4];
            3'd2: y = data[8  +: 4];
            3'd3: y = data[12 +: 4];
            3'd4: y = data[16 +: 4];
            3'd5: y = data[20 +: 4];
            3'd6: y = data[24 +: 4];
            3'd7: y = data[28 +: 4];
        endcase
    end

    // The same logical selector is intentionally presented in a different
    // concatenation order. Each label is remapped so z(data, sel) remains a
    // normal complete lookup table over the original selector value.
    always @* begin
        z = 0;
        case ({sel[1], sel[2], sel[0]})
            3'd0: z = data[4  +: 4];
            3'd1: z = data[0  +: 4];
            3'd4: z = data[12 +: 4];
            3'd5: z = data[8  +: 4];
            3'd2: z = data[20 +: 4];
            3'd3: z = data[16 +: 4];
            3'd6: z = data[28 +: 4];
            3'd7: z = data[24 +: 4];
        endcase
    end
endmodule
