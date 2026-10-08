// Variable-order fixture: sel[2] ? sel[0] : sel[1] is smallest with bit 2 outermost.
module selector_order_search(
    input [2:0] sel,
    input [7:0] a,
    input [7:0] b,
    output reg [7:0] y
);
always @* begin
    y = 8'h00;
    case (sel)
        3'd0: y = a;
        3'd1: y = a;
        3'd2: y = b;
        3'd3: y = b;
        3'd4: y = a;
        3'd5: y = b;
        3'd6: y = a;
        3'd7: y = b;
    endcase
end
endmodule
